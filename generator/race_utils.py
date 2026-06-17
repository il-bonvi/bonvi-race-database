#!/usr/bin/env python3
"""
race_utils.py — Modulo condiviso per genera_report.py e gestisci_gare.py.

Contiene:
  - Costanti condivise (CATEGORIE, GENERI, DISCIPLINE)
  - slugify / categoria_code / get_slug_suffix
  - parse_gpx / haversine
  - reverse_geocode  (con retry + backoff esponenziale)
  - update_gares_index
  - bump_date_year
"""

import re
import json
import math
import time
import logging
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, date
from pathlib import Path

logger = logging.getLogger(__name__)

# ── COSTANTI ──────────────────────────────────────────────────────────────────

CATEGORIE  = ["Elite", "U23", "Junior", "Allievi"]
GENERI     = ["Maschile", "Femminile"]
DISCIPLINE = ["Strada", "Criterium", "ITT", "TTT", "Tipo pista"]


# ── SLUG ──────────────────────────────────────────────────────────────────────

def slugify(s: str) -> str:
    """Converte una stringa in slug URL-safe."""
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = s.lower()
    s = re.sub(r'[^a-z0-9]+', '-', s)
    return s.strip('-')


def categoria_code(genere: str, categoria: str) -> str:
    """
    Genera il codice categoria combinando genere e categoria.

    Genere:   "Maschile" → M  |  "Femminile" → D
    Categoria: "Elite" → ELI  |  "U23" → U  |  "Junior" → J  |  "Allievi" → A

    Esempio: categoria_code("Femminile", "Elite") → "DELI"
    """
    genere_map    = {"Maschile": "M",   "Femminile": "D"}
    categoria_map = {"Elite": "ELI",    "U23": "U",    "Junior": "J",    "Allievi": "A"}

    g = genere_map.get(genere, "")
    c = categoria_map.get(categoria, "")
    return f"{g}{c}" if g and c else ""


def get_slug_suffix(genere: str, categoria: str, is_wt: bool) -> str:
    """
    Genera il suffisso dello slug considerando il flag WT.

    Se is_wt=True:  "Maschile" → "MWT"  |  "Femminile" → "DWT"
    Se is_wt=False: usa categoria_code() normale.

    Esempio:
      get_slug_suffix("Femminile", "Elite", True)  → "DWT"
      get_slug_suffix("Femminile", "Elite", False) → "DELI"
    """
    if is_wt:
        return {"Maschile": "MWT", "Femminile": "DWT"}.get(genere, "")
    return categoria_code(genere, categoria)


# ── PARSING GPX ───────────────────────────────────────────────────────────────

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distanza in metri tra due coordinate geografiche (formula di Haversine)."""
    R = 6_371_000
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dφ = math.radians(lat2 - lat1)
    dλ = math.radians(lon2 - lon1)
    a = math.sin(dφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(dλ / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def parse_gpx(gpx_path: Path) -> dict:
    """
    Estrae distanza (km), dislivello positivo (m), punti GPS e coordinate
    del punto d'arrivo da un file GPX.

    Ritorna un dict con le chiavi:
      distanza_km, dislivello_m, center_lat, center_lon, gpx_points
    Tutti i valori possono essere None in caso di errore o dati assenti.
    """
    _empty = {
        'distanza_km': None,
        'dislivello_m': None,
        'center_lat': None,
        'center_lon': None,
        'gpx_points': None,
    }

    try:
        tree = ET.parse(gpx_path)
        root = tree.getroot()

        ns = ''
        if root.tag.startswith('{'):
            ns = root.tag.split('}')[0] + '}'

        points = root.findall(f'.//{ns}trkpt') or root.findall(f'.//{ns}rtept')
        if not points:
            return _empty

        coords     = []
        gpx_points = []

        for pt in points:
            try:
                lat = float(pt.get('lat'))
                lon = float(pt.get('lon'))
                ele_el = pt.find(f'{ns}ele')
                ele = float(ele_el.text) if ele_el is not None else None
                coords.append((lat, lon, ele))
                gpx_points.append({
                    'lat': round(lat, 6),
                    'lon': round(lon, 6),
                    'ele': round(ele, 1) if ele is not None else None,
                })
            except (TypeError, ValueError):
                continue

        if not coords:
            return _empty

        # Distanza totale
        dist_m = sum(
            _haversine(coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1])
            for i in range(len(coords) - 1)
        )

        # Dislivello positivo calcolato sui punti già arrotondati (coerente con gara.html)
        d_plus   = 0.0
        prev_ele = None
        for pt in gpx_points:
            ele = pt.get('ele')
            if ele is None:
                prev_ele = None
                continue
            if prev_ele is not None and ele > prev_ele:
                d_plus += ele - prev_ele
            prev_ele = ele

        # Punto d'arrivo come centro approssimativo per il geocoding
        finish     = coords[-1]
        center_lat = finish[0]
        center_lon = finish[1]

        return {
            'distanza_km':  round(dist_m / 1000, 2),
            'dislivello_m': round(d_plus) if d_plus > 0 else None,
            'center_lat':   center_lat,
            'center_lon':   center_lon,
            'gpx_points':   gpx_points,
        }

    except Exception as exc:
        logger.warning("Impossibile leggere dati dal GPX '%s': %s", gpx_path, exc)
        return _empty


# ── REVERSE GEOCODING ─────────────────────────────────────────────────────────

def reverse_geocode(lat: float, lon: float) -> str | None:
    """
    Ritorna 'Provincia, IT' tramite Nominatim (OpenStreetMap).
    Nessuna API key richiesta.

    Implementa retry con backoff esponenziale (1 s, 2 s, 4 s) per gestire
    timeout e servizi sovraccarichi.
    Ritorna None se offline o in caso di errore definitivo.
    """
    max_retries = 3

    for attempt in range(max_retries):
        try:
            params = urllib.parse.urlencode({
                "lat":            round(lat, 5),
                "lon":            round(lon, 5),
                "format":         "json",
                "zoom":           8,           # livello regione/provincia
                "addressdetails": 1,
            })
            url = f"https://nominatim.openstreetmap.org/reverse?{params}"
            req = urllib.request.Request(url, headers={"User-Agent": "race-db-archivio/1.0"})

            # Timeout generoso — Nominatim può essere lento
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())

            addr     = data.get("address", {})
            provincia = (
                addr.get("county")  or
                addr.get("city")    or
                addr.get("town")    or
                addr.get("village") or
                addr.get("state")   or
                ""
            )

            # Rimuovi prefissi verbosi tipo "Provincia di Varese" → "Varese"
            for prefix in ("Provincia di ", "Province of ", "Distretto di "):
                if provincia.startswith(prefix):
                    provincia = provincia[len(prefix):]

            country_code = addr.get("country_code", "").upper()
            parts        = [p for p in [provincia, country_code] if p]
            result       = ", ".join(parts) if parts else None
            logger.debug("reverse_geocode(%s, %s) → %s", lat, lon, result)
            return result

        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            if attempt < max_retries - 1:
                wait = 2 ** attempt        # 1 s, 2 s
                logger.warning(
                    "reverse_geocode tentativo %d/%d fallito (%s). Retry tra %ds…",
                    attempt + 1, max_retries, type(exc).__name__, wait,
                )
                time.sleep(wait)
            else:
                logger.error(
                    "reverse_geocode FALLITO dopo %d tentativi per (%s, %s): %s",
                    max_retries, lat, lon, exc,
                )
                return None

        except Exception as exc:
            logger.error("reverse_geocode ERRORE FATALE (%s, %s): %s", lat, lon, exc)
            return None

    return None


# ── INDICE GARE ───────────────────────────────────────────────────────────────

def update_gares_index(gare_dir: Path, archivio_dir: Path) -> None:
    """
    Scansiona gare_dir/*.json e riscrive public/gare-index.json con i metadati
    essenziali per la navigazione tra serie nel frontend.

    Le tappe individuali (tipo == 'tappa') vengono escluse dall'indice.
    """
    if not gare_dir.exists():
        logger.warning("update_gares_index: cartella '%s' non trovata", gare_dir)
        return

    races = []
    for json_file in sorted(gare_dir.glob("*.json")):
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                gara = json.load(f)

            slug = gara.get("slug")
            if not slug:
                continue

            # Le tappe individuali non vanno nell'indice
            if gara.get('tipo') == 'tappa':
                continue

            data_str  = gara.get("data", "")
            year      = data_str.split("-")[0] if data_str else "unknown"
            genere    = gara.get("genere", "")
            cat_raw   = gara.get("categoria", [])

            # Normalizza sempre a lista
            cat_display = cat_raw if isinstance(cat_raw, list) else ([cat_raw] if cat_raw else [])
            cat_first   = cat_display[0] if cat_display else ""
            cat_code    = categoria_code(genere, cat_first) if genere and cat_first else ""

            races.append({
                "slug":         slug,
                "titolo":       gara.get("titolo"),
                "data":         data_str,
                "year":         year,
                "race_series":  gara.get("race_series"),
                "genere":       genere,
                "categoria":    cat_display,
                "categoria_code": cat_code,
                "tipo":         gara.get("tipo"),
                "n_tappe":      gara.get("n_tappe"),
                "wt":           gara.get("wt", False),
            })

        except Exception as exc:
            logger.warning("update_gares_index: impossibile leggere '%s': %s", json_file, exc)
            continue

    index_path = archivio_dir / "public" / "gare-index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(index_path, 'w', encoding='utf-8') as f:
            json.dump(races, f, indent=2, ensure_ascii=False)
        logger.debug("update_gares_index: scritte %d gare in '%s'", len(races), index_path)
    except Exception as exc:
        logger.error("update_gares_index: impossibile scrivere '%s': %s", index_path, exc)


# ── UTILITÀ DATA ──────────────────────────────────────────────────────────────

def bump_date_year(date_str: str, years: int = 1) -> str:
    """
    Aumenta l'anno di una data AAAA-MM-GG di `years` anni.
    Se la data non è valida (es. 29 feb in anno non bisestile), ritorna l'input invariato.
    """
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
    except (TypeError, ValueError):
        return date_str
    try:
        return dt.replace(year=dt.year + years).strftime("%Y-%m-%d")
    except ValueError:
        return date_str


def validate_date_string(date_str: str) -> bool:
    """Ritorna True se date_str è una data valida nel formato AAAA-MM-GG."""
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return False
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except ValueError:
        return False