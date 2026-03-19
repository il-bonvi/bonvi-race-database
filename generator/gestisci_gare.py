#!/usr/bin/env python3
"""
gestisci_gare.py — Gestore GUI per le gare (list, view, edit, delete, add).

Uso:
    python generator/gestisci_gare.py

Funzionalità:
  - Elenco di tutte le gare nel database con filtri e sorting
  - Filtri: anno-mese, genere, categoria, disciplina
  - Ricerca per titolo/giro
  - Sort per data, km, nome
  - Visualizza dettagli race (metadati + GPX)
  - Modifica metadati race
  - Elimina race dal database
  - Aggiungi nuova race (riusa dialog genera_report.py)
"""

import sys
import json
import re
import math
from datetime import datetime, date
from tkinter import ttk, filedialog
import tkinter as tk
from tkinter import messagebox
from pathlib import Path
import xml.etree.ElementTree as ET

ARCHIVIO_DIR = Path(__file__).parent.parent

# Cartelle sorgenti
GARE_DIR    = ARCHIVIO_DIR / "gare-sorgenti" / "dettagli"   # dettagli gara
GPX_DIR     = ARCHIVIO_DIR / "gare-sorgenti" / "gpx"        # file gpx separati
GARE_DIR.mkdir(parents=True, exist_ok=True)
GPX_DIR.mkdir(parents=True, exist_ok=True)

# Mirror pubblici (serviti dal browser)
PUBLIC_GARE_DIR = ARCHIVIO_DIR / "public" / "gare-sorgenti" / "dettagli"
PUBLIC_GPX_DIR  = ARCHIVIO_DIR / "public" / "gare-sorgenti" / "gpx"
PUBLIC_GARE_DIR.mkdir(parents=True, exist_ok=True)
PUBLIC_GPX_DIR.mkdir(parents=True, exist_ok=True)


# ── UTILITY FUNCTIONS ─────────────────────────────────────────────────────────

def slugify(s: str) -> str:
    """Converte una stringa in slug URL-safe"""
    import unicodedata
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = s.lower()
    s = re.sub(r'[^a-z0-9]+', '-', s)
    return s.strip('-')


def categoria_code(genere: str, categoria: str) -> str:
    """
    Genera il codice categoria combinando genere e categoria.
    
    Genere:
      - "Maschile" → M
      - "Femminile" → D
    
    Categoria:
      - "Elite" → PRO
      - "U23" → U
      - "Junior" → J
      - "Allievi" → A
    
    Esempio: categoria_code("Femminile", "Elite") → "DPRO"
    """
    genere_map = {
        "Maschile": "M",
        "Femminile": "D"
    }
    
    categoria_map = {
        "Elite": "PRO",
        "U23": "U",
        "Junior": "J",
        "Allievi": "A"
    }
    
    genere_code = genere_map.get(genere, "")
    cat_code = categoria_map.get(categoria, "")
    
    return f"{genere_code}{cat_code}" if genere_code and cat_code else ""


def parse_gpx(gpx_path: Path) -> dict:
    """Estrae distanza (km), dislivello positivo (m) e punti GPX dal file GPX."""
    try:
        tree = ET.parse(gpx_path)
        root = tree.getroot()
        ns = ''
        if root.tag.startswith('{'):
            ns = root.tag.split('}')[0] + '}'

        points = root.findall(f'.//{ns}trkpt')
        if not points:
            points = root.findall(f'.//{ns}rtept')

        if not points:
            return {'distanza_km': None, 'dislivello_m': None, 'gpx_points': None}

        coords = []
        gpx_points = []  # Punti per il JSON
        for pt in points:
            try:
                lat = float(pt.get('lat'))
                lon = float(pt.get('lon'))
                ele_el = pt.find(f'{ns}ele')
                ele = float(ele_el.text) if ele_el is not None else None
                coords.append((lat, lon, ele))
                # Salva punti per il JSON (arrotondati per ridurre dimensione)
                gpx_points.append({
                    'lat': round(lat, 6),
                    'lon': round(lon, 6),
                    'ele': round(ele, 1) if ele is not None else None
                })
            except (TypeError, ValueError):
                continue

        if not coords:
            return {'distanza_km': None, 'dislivello_m': None, 'gpx_points': None}

        def haversine(lat1, lon1, lat2, lon2):
            R = 6371000
            φ1, φ2 = math.radians(lat1), math.radians(lat2)
            dφ = math.radians(lat2 - lat1)
            dλ = math.radians(lon2 - lon1)
            a = math.sin(dφ/2)**2 + math.cos(φ1)*math.cos(φ2)*math.sin(dλ/2)**2
            return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

        dist_m = sum(
            haversine(coords[i][0], coords[i][1], coords[i+1][0], coords[i+1][1])
            for i in range(len(coords)-1)
        )

        # Smoothing quote con media mobile (finestra 5) per ridurre rumore GPS
        eles_raw = [c[2] for c in coords if c[2] is not None]
        w = 5
        eles = []
        for i in range(len(eles_raw)):
            start = max(0, i - w // 2)
            end   = min(len(eles_raw), i + w // 2 + 1)
            eles.append(sum(eles_raw[start:end]) / (end - start))

        d_plus = 0.0
        for i in range(1, len(eles)):
            diff = eles[i] - eles[i-1]
            if diff > 0:
                d_plus += diff

        # Punto di arrivo per il geocoding (ultimo punto del tracciato)
        finish = coords[-1]
        center_lat, center_lon = finish[0], finish[1]

        return {
            'distanza_km': round(dist_m / 1000, 2),
            'dislivello_m': round(d_plus) if d_plus > 0 else None,
            'gpx_points':   gpx_points,
            'center_lat': center_lat,
            'center_lon': center_lon,
        }

    except Exception as e:
        messagebox.showerror("Errore", f"Impossibile leggere il GPX: {e}")
        return {'distanza_km': None, 'dislivello_m': None, 'gpx_points': None, 'center_lat': None, 'center_lon': None}


# ── REVERSE GEOCODING (NOMINATIM/OSM) ────────────────────────────────────────

def reverse_geocode(lat: float, lon: float) -> str | None:
    """
    Ritorna 'Provincia, IT' tramite Nominatim (OpenStreetMap).
    Nessuna API key richiesta. Ritorna None se offline o in caso di errore.
    """
    import urllib.request
    import urllib.parse
    import json as _json

    try:
        params = urllib.parse.urlencode({
            "lat": round(lat, 5),
            "lon": round(lon, 5),
            "format": "json",
            "zoom": 8,
            "addressdetails": 1,
        })
        url = f"https://nominatim.openstreetmap.org/reverse?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "race-db-archivio/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = _json.loads(resp.read())

        addr = data.get("address", {})
        provincia = (
            addr.get("county") or
            addr.get("city") or
            addr.get("town") or
            addr.get("village") or
            ""
        )
        for prefix in ("Provincia di ", "Province of ", "Distretto di "):
            if provincia.startswith(prefix):
                provincia = provincia[len(prefix):]

        country_code = addr.get("country_code", "").upper()
        parts = [p for p in [provincia, country_code] if p]
        return ", ".join(parts) if parts else None
    except Exception:
        return None


# ── AUTO-UPDATE INDICE GARE ──────────────────────────────────────────────────

def update_gares_index():
    """Genera automaticamente gare-index.json per la navigazione tra serie."""
    races = []
    
    # Scansiona tutti i file JSON
    for json_file in sorted(GARE_DIR.glob("*.json")):
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                gara = json.load(f)
            
            slug = gara.get("slug")
            if not slug:
                continue
            
            # Estrai l'anno dalla data (formato AAAA-MM-GG)
            data_str = gara.get("data", "")
            year = data_str.split("-")[0] if data_str else "unknown"
            
            # Estrai genere e categoria per generare il codice categoria
            genere = gara.get("genere", "")
            categoria_list = gara.get("categoria", [])
            # Memorizza tutte le categorie
            categoria_display = categoria_list if isinstance(categoria_list, list) else ([categoria_list] if categoria_list else [])
            # Per il codice, usa la prima categoria
            categoria_first = categoria_list[0] if categoria_list else ""
            cat_code = categoria_code(genere, categoria_first) if genere and categoria_first else ""
            
            # Salta le singole tappe (sono incluse nella scheda corsa a tappe)
            if gara.get('tipo') == 'tappa':
                continue

            races.append({
                "slug": slug,
                "titolo": gara.get("titolo"),
                "data": data_str,
                "year": year,
                "race_series": gara.get("race_series"),
                "genere": genere,
                "categoria": categoria_display,
                "categoria_code": cat_code,
                "tipo": gara.get("tipo"),
                "n_tappe": gara.get("n_tappe"),
                "wt": gara.get("wt", False),
            })
            
        except Exception:
            continue
    
    # Salva l'index
    index_path = ARCHIVIO_DIR / "public" / "gare-index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        with open(index_path, 'w', encoding='utf-8') as f:
            json.dump(races, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


# ── ESTRAZIONE SERIE ──────────────────────────────────────────────────────────

def get_all_race_series() -> list:
    """Estrae tutte le serie uniche dai dati delle gare (escludendo tappe individuali)."""
    series_set = set()
    
    for json_file in GARE_DIR.glob("*.json"):
        try:
            data = json.loads(json_file.read_text(encoding='utf-8'))
            # Salta le tappe individuali (mantieni solo corsa_a_tappe e gare singole)
            if data.get('tipo') == 'tappa':
                continue
            
            race_series = data.get('race_series', '')
            if race_series:
                series_set.add(race_series)
        except Exception:
            continue
    
    return sorted(list(series_set))


CATEGORIE = ["Elite", "U23", "Junior", "Allievi"]
GENERI = ["Maschile", "Femminile"]
DISCIPLINE = ["Strada", "Criterium", "ITT", "TTT", "Tipo pista"]

BG = "#ede9e2"
ACCENT = "#fc5200"
FG = "#1a1a1a"


# ── UTILITÀ ──────────────────────────────────────────────────────────────────

def load_all_races():
    """Carica tutte le gare da gare-sorgenti/"""
    races = []
    for json_file in sorted(GARE_DIR.glob("*.json")):
        try:
            data = json.loads(json_file.read_text(encoding='utf-8'))
            races.append((data.get("slug", "?"), data))
        except Exception:
            pass
    return races


def save_race(slug: str, data: dict):
    """Salva i dettagli gara in gare-sorgenti/dettagli/ e, se presenti, i punti
    GPX in gare-sorgenti/gpx/{slug}-gpx.json. Sincronizza in public/.
    """
    # Imposta race_series automaticamente dal titolo solo se mancante/vuota
    if not data.get('race_series'):
        titolo = data.get('titolo')
        if titolo:
            data['race_series'] = slugify(titolo)
    else:
        # Converti a minuscolo per evitare inconsistenze
        data['race_series'] = data.get('race_series', '').lower().strip()

    # ── Estrai gpx_points (vanno nel file separato) ──────────────────────────
    gpx_points = data.pop('gpx_points', None)

    # ── Salva dettagli ────────────────────────────────────────────────────────
    json_path = GARE_DIR / f"{slug}.json"
    data_clean = {k: v for k, v in data.items() if v is not None}
    json_str = json.dumps(data_clean, ensure_ascii=False, indent=2)
    json_path.write_text(json_str, encoding='utf-8')
    PUBLIC_GARE_DIR.mkdir(parents=True, exist_ok=True)
    (PUBLIC_GARE_DIR / f"{slug}.json").write_text(json_str, encoding='utf-8')

    # ── Salva GPX separato (solo se fornito) ──────────────────────────────────
    if gpx_points:
        gpx_data = {"slug": slug, "gpx_points": gpx_points}
        gpx_str = json.dumps(gpx_data, ensure_ascii=False, indent=2)
        GPX_DIR.mkdir(parents=True, exist_ok=True)
        (GPX_DIR / f"{slug}-gpx.json").write_text(gpx_str, encoding='utf-8')
        PUBLIC_GPX_DIR.mkdir(parents=True, exist_ok=True)
        (PUBLIC_GPX_DIR / f"{slug}-gpx.json").write_text(gpx_str, encoding='utf-8')

    # Aggiorna l'indice per la navigazione tra serie
    update_gares_index()


def delete_race(slug: str):
    """Elimina dettagli e file GPX dalla sorgente e da public/."""
    # Dettagli
    for p in [GARE_DIR / f"{slug}.json", PUBLIC_GARE_DIR / f"{slug}.json"]:
        if p.exists():
            p.unlink()

    # File GPX separato
    for p in [GPX_DIR / f"{slug}-gpx.json", PUBLIC_GPX_DIR / f"{slug}-gpx.json"]:
        if p.exists():
            p.unlink()

    # Aggiorna l'indice per la navigazione tra serie
    update_gares_index()


def save_stage_race(race_slug: str, main_data: dict, stages: list):
    """Salva una corsa a tappe con le sue tappe.
    
    - race_slug: slug della corsa principale
    - main_data: dati principali (titolo, data, genere, categoria, luogo, ...)
    - stages: lista di dict con i dati di ogni tappa:
        {numero, nome, slug_tappa, data, distanza_km, dislivello_m, disciplina, gpx_points (opz.)}
    """
    # Calcola totali dalle tappe
    total_km  = sum(float(s.get('distanza_km') or 0) for s in stages)
    total_elev = sum(float(s.get('dislivello_m') or 0) for s in stages)

    # Array tappe (solo metadata per il JSON principale)
    tappe_meta = []
    for s in stages:
        tappa_meta = {
            "numero":       s['numero'],
            "nome":         s['nome'],
            "slug":         s['slug_tappa'],
            "data":         s.get('data', ''),
            "distanza_km":  s.get('distanza_km'),
            "dislivello_m": s.get('dislivello_m'),
            "disciplina":   s.get('disciplina', 'Strada'),
            "giri":         s.get('giri', 1) if s.get('giri', 1) > 1 else None,
        }
        tappe_meta.append({k: v for k, v in tappa_meta.items() if v is not None})

    # Aggiorna i campi del main_data
    main_data['tipo']         = 'corsa_a_tappe'
    main_data['n_tappe']      = len(stages)
    main_data['distanza_km']  = round(total_km, 2) if total_km else None
    main_data['dislivello_m'] = round(total_elev)  if total_elev else None
    main_data['tappe']        = tappe_meta
    main_data['slug']         = race_slug
    if not main_data.get('race_series'):
        main_data['race_series'] = slugify(main_data.get('titolo', ''))
    else:
        # Converti a minuscolo per evitare inconsistenze
        main_data['race_series'] = main_data.get('race_series', '').lower().strip()

    # Salva JSON principale
    main_clean = {k: v for k, v in main_data.items() if v is not None}
    main_str = json.dumps(main_clean, ensure_ascii=False, indent=2)
    (GARE_DIR / f"{race_slug}.json").write_text(main_str, encoding='utf-8')
    PUBLIC_GARE_DIR.mkdir(parents=True, exist_ok=True)
    (PUBLIC_GARE_DIR / f"{race_slug}.json").write_text(main_str, encoding='utf-8')

    # Salva ogni tappa come JSON separato + GPX se disponibile
    for s in stages:
        stage_slug = s['slug_tappa']
        stage_data = {
            "titolo":               f"{main_data['titolo']} — Tappa {s['numero']}: {s['nome']}",
            "tipo":                 "tappa",
            "nome_tappa":           s['nome'],
            "numero_tappa":         s['numero'],
            "corsa_a_tappe_slug":   race_slug,
            "corsa_a_tappe_titolo": main_data['titolo'],
            "race_series":          main_data.get('race_series', ''),
            "data":                 s.get('data', ''),
            "genere":               main_data.get('genere', ''),
            "categoria":            main_data.get('categoria', []),
            "disciplina":           s.get('disciplina', 'Strada'),
            "distanza_km":          s.get('distanza_km'),
            "dislivello_m":         s.get('dislivello_m'),
            "velocita_media_kmh":   s.get('velocita_media_kmh'),
            "luogo":                s.get('luogo') or main_data.get('luogo'),
            "slug":                 stage_slug,
        }
        # Eredita WT dalla corsa a tappe principale
        if main_data.get('wt'):
            stage_data['wt'] = True
        stage_clean = {k: v for k, v in stage_data.items() if v is not None}
        stage_str = json.dumps(stage_clean, ensure_ascii=False, indent=2)
        (GARE_DIR / f"{stage_slug}.json").write_text(stage_str, encoding='utf-8')
        (PUBLIC_GARE_DIR / f"{stage_slug}.json").write_text(stage_str, encoding='utf-8')

        gpx_points = s.get('gpx_points')
        if gpx_points:
            gpx_data = {"slug": stage_slug, "gpx_points": gpx_points}
            gpx_str  = json.dumps(gpx_data, ensure_ascii=False, indent=2)
            GPX_DIR.mkdir(parents=True, exist_ok=True)
            (GPX_DIR / f"{stage_slug}-gpx.json").write_text(gpx_str, encoding='utf-8')
            PUBLIC_GPX_DIR.mkdir(parents=True, exist_ok=True)
            (PUBLIC_GPX_DIR / f"{stage_slug}-gpx.json").write_text(gpx_str, encoding='utf-8')

    update_gares_index()


def delete_stage_race(slug: str, tappe: list):
    """Elimina una corsa a tappe e tutte le sue tappe."""
    # File principale
    for p in [GARE_DIR / f"{slug}.json", PUBLIC_GARE_DIR / f"{slug}.json"]:
        if p.exists():
            p.unlink()

    # Ogni tappa
    for tappa in tappe:
        stage_slug = tappa.get('slug', '')
        if not stage_slug:
            continue
        for p in [
            GARE_DIR / f"{stage_slug}.json",
            PUBLIC_GARE_DIR / f"{stage_slug}.json",
            GPX_DIR / f"{stage_slug}-gpx.json",
            PUBLIC_GPX_DIR / f"{stage_slug}-gpx.json",
        ]:
            if p.exists():
                p.unlink()

    update_gares_index()


def git_push_changes(message: str = None) -> tuple:
    """Esegue git add, commit e push automatico.
    
    Returns:
        (success: bool, message: str)
    """
    import subprocess
    import os
    
    try:
        # Configura Git per non richiedere interattivamente le credenziali
        env = os.environ.copy()
        env['GIT_TERMINAL_PROMPT'] = '0'
        
        # git add
        subprocess.run(
            ["git", "add", "."],
            cwd=ARCHIVIO_DIR,
            capture_output=True,
            text=True,
            check=True,
            env=env
        )
        
        # git commit (con messaggio di default se non fornito)
        if not message:
            message = f"Update races database - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        
        result = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=ARCHIVIO_DIR,
            capture_output=True,
            text=True,
            env=env
        )
        
        # Se non c'è nulla da committare, va bene comunque
        if result.returncode != 0 and "nothing to commit" not in result.stdout:
            return False, f"Errore commit: {result.stderr}"
        
        # git push con credenziali configurate
        result = subprocess.run(
            ["git", "push"],
            cwd=ARCHIVIO_DIR,
            capture_output=True,
            text=True,
            env=env,
            timeout=10
        )
        
        # Verifica se il push è stato successful (anche se returncode != 0, potrebbe essere solo un warning)
        output = result.stdout + result.stderr
        
        # Controllare se c'è un errore reale
        if "fatal:" in result.stderr and result.returncode != 0:
            if "could not read" in result.stderr:
                return False, "❌ Errore autenticazione Git:\nConfigura le credenziali con:\n  git config --global credential.helper store"
            else:
                return False, f"❌ Errore git: {result.stderr}"
        
        # Se non ci sono errori fatali, il push è riuscito
        return True, "✅ Push completato con successo!"
        
    except subprocess.TimeoutExpired:
        return False, "❌ Timeout: Push impiegato troppo tempo"
    except subprocess.CalledProcessError as e:
        return False, f"Errore git: {e.stderr}"
    except FileNotFoundError:
        return False, "❌ Git non trovato. Assicurati che git sia installato."
    except Exception as e:
        return False, f"❌ Errore inaspettato: {str(e)}"


# ── MAIN GUI ──────────────────────────────────────────────────────────────────

class RaceManagerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("📋 Gestore Gare")
        self.root.state('zoomed')
        self.root.configure(bg=BG)
        
        self.root.option_add("*Background", BG)
        self.root.option_add("*Foreground", FG)
        self.root.option_add("*Font", ("Helvetica", 10))
        
        self.all_races = []  # Cache di tutte le gare
        self.filtered_races = []  # Gare filtrate
        self.expanded_stages = set()  # Slug delle corse a tappe expand nel listbox
        self.listbox_index_map = {}  # Mapping da indice listbox a slug gara/tappa
        
        # State filtri
        self.filter_state = {
            'anno_mese': 'all',
            'genere': 'all',
            'categoria': 'all',
            'disciplina': 'all',
            'search': '',
            'sort': 'data-asc'
        }
        
        # Header
        header = tk.Frame(self.root, bg=ACCENT, height=60)
        header.pack(side="top", fill="x")
        header.pack_propagate(False)
        
        title = tk.Label(header, text="📋 Gestore Gare", font=("Helvetica", 18, "bold"), 
                        bg=ACCENT, fg="white")
        title.pack(pady=12)
        
        # Filters Panel
        filters_frame = tk.Frame(self.root, bg=BG)
        filters_frame.pack(side="top", fill="x", padx=12, pady=12)
        
        # Row 1: Anno-Mese + Search
        row1 = tk.Frame(filters_frame, bg=BG)
        row1.pack(fill="x", pady=(0, 8))
        
        tk.Label(row1, text="Anno-Mese:", font=("Helvetica", 9, "bold"), bg=BG).pack(side="left", padx=(0, 6))
        self.anno_mese_var = tk.StringVar(value="all")
        self.anno_mese_combo = ttk.Combobox(row1, textvariable=self.anno_mese_var, width=15, state="readonly")
        self.anno_mese_combo.pack(side="left", padx=(0, 20))
        self.anno_mese_combo.bind("<<ComboboxSelected>>", lambda e: self.apply_filters())
        
        tk.Label(row1, text="Ricerca giro:", font=("Helvetica", 9, "bold"), bg=BG).pack(side="left", padx=(0, 6))
        self.search_var = tk.StringVar()
        self.search_entry = tk.Entry(row1, textvariable=self.search_var, width=30)
        self.search_entry.pack(side="left", padx=(0, 20))
        self.search_var.trace("w", lambda *args: self.apply_filters())
        
        tk.Label(row1, text="Ordina:", font=("Helvetica", 9, "bold"), bg=BG).pack(side="left", padx=(0, 6))
        self.sort_var = tk.StringVar(value="data-asc")
        sort_combo = ttk.Combobox(row1, textvariable=self.sort_var, width=15, 
                                  values=["data-asc", "data-desc", "km-asc", "km-desc", "nome"],
                                  state="readonly")
        sort_combo.pack(side="left")
        sort_combo.bind("<<ComboboxSelected>>", lambda e: self.apply_filters())
        
        # Row 2: Genere, Categoria, Disciplina
        row2 = tk.Frame(filters_frame, bg=BG)
        row2.pack(fill="x", pady=(0, 8))
        
        tk.Label(row2, text="Genere:", font=("Helvetica", 9, "bold"), bg=BG).pack(side="left", padx=(0, 6))
        self.genere_var = tk.StringVar(value="all")
        genere_combo = ttk.Combobox(row2, textvariable=self.genere_var, 
                                    values=["all"] + GENERI, width=15, state="readonly")
        genere_combo.pack(side="left", padx=(0, 20))
        genere_combo.bind("<<ComboboxSelected>>", lambda e: self.apply_filters())
        
        tk.Label(row2, text="Categoria:", font=("Helvetica", 9, "bold"), bg=BG).pack(side="left", padx=(0, 6))
        self.categoria_var = tk.StringVar(value="all")
        categoria_combo = ttk.Combobox(row2, textvariable=self.categoria_var,
                                       values=["all"] + CATEGORIE, width=15, state="readonly")
        categoria_combo.pack(side="left", padx=(0, 20))
        categoria_combo.bind("<<ComboboxSelected>>", lambda e: self.apply_filters())
        
        tk.Label(row2, text="Disciplina:", font=("Helvetica", 9, "bold"), bg=BG).pack(side="left", padx=(0, 6))
        self.disciplina_var = tk.StringVar(value="all")
        disciplina_combo = ttk.Combobox(row2, textvariable=self.disciplina_var,
                                        values=["all"] + DISCIPLINE, width=15, state="readonly")
        disciplina_combo.pack(side="left", padx=(0, 20))
        disciplina_combo.bind("<<ComboboxSelected>>", lambda e: self.apply_filters())
        
        tk.Button(row2, text="Azzera filtri", font=("Helvetica", 9), bg="#d1d5db", 
                 fg=FG, padx=12, pady=4, relief="flat", bd=0, command=self.reset_filters).pack(side="left")
        
        # Content
        content = tk.Frame(self.root, bg=BG)
        content.pack(side="top", fill="both", expand=True, padx=12, pady=12)
        
        # Left: List with details
        left = tk.Frame(content, bg=BG)
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))
        
        tk.Label(left, text="Gare nel database:", font=("Helvetica", 11, "bold"), bg=BG).pack(anchor="w", pady=(0, 6))
        
        list_frame = tk.Frame(left, bg="white", relief="solid", bd=1)
        list_frame.pack(fill="both", expand=True)
        
        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")
        
        self.race_listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set, bg="white", 
                                       selectmode="single", font=("Courier", 9), bd=0)
        self.race_listbox.pack(side="left", fill="both", expand=True)
        self.race_listbox.bind("<<ListboxSelect>>", self.on_race_select)
        self.race_listbox.bind("<Double-Button-1>", self.on_race_double_click)
        scrollbar.config(command=self.race_listbox.yview)
        
        # Right: Details
        right = tk.Frame(content, bg=BG)
        right.pack(side="right", fill="both", expand=True, padx=(6, 0))
        
        tk.Label(right, text="Dettagli gara:", font=("Helvetica", 11, "bold"), bg=BG).pack(anchor="w", pady=(0, 6))
        
        self.info_frame = tk.Frame(right, bg="white", relief="solid", bd=1)
        self.info_frame.pack(fill="both", expand=True, padx=0, pady=0)
        
        self.info_text = tk.Text(self.info_frame, bg="white", fg=FG, font=("Courier", 9), 
                                height=20, wrap="word", relief="flat", bd=0, padx=8, pady=8)
        self.info_text.pack(fill="both", expand=True)
        self.info_text.config(state="disabled")
        
        # Buttons
        button_frame = tk.Frame(self.root, bg=BG)
        button_frame.pack(side="bottom", fill="x", padx=12, pady=12)
        
        tk.Button(button_frame, text="➕ Aggiungi corsa", font=("Helvetica", 10),
                 bg=ACCENT, fg="white", padx=12, pady=8, relief="flat", bd=0,
                 cursor="hand2", command=self.add_race).pack(side="left", padx=(0, 6))
        
        tk.Button(button_frame, text="➕ Aggiungi corsa a tappe", font=("Helvetica", 10),
                 bg="#059669", fg="white", padx=12, pady=8, relief="flat", bd=0,
                 cursor="hand2", command=self.add_stage_race).pack(side="left", padx=(0, 6))
        
        tk.Button(button_frame, text="✏️ Modifica", font=("Helvetica", 10),
                 bg="#9ca3af", fg="white", padx=12, pady=8, relief="flat", bd=0,
                 cursor="hand2", command=self.edit_race).pack(side="left", padx=6)
        
        tk.Button(button_frame, text="🗑️ Elimina", font=("Helvetica", 10),
                 bg="#dc2626", fg="white", padx=12, pady=8, relief="flat", bd=0,
                 cursor="hand2", command=self.delete_race).pack(side="left", padx=6)
        
        tk.Button(button_frame, text="📤 Push", font=("Helvetica", 10),
                 bg="#8b5cf6", fg="white", padx=12, pady=8, relief="flat", bd=0,
                 cursor="hand2", command=self.push_changes).pack(side="left", padx=6)
        
        self.refresh_list()
    
    def refresh_list(self):
        """Ricarica lista gare e popola filtri anno-mese"""
        self.all_races = load_all_races()
        
        # Popola combo anno-mese
        anni_mesi = set()
        for slug, data in self.all_races:
            data_str = data.get("data", "")
            if len(data_str) >= 7:
                anni_mesi.add(data_str[:7])
        
        anni_mesi_sorted = sorted(anni_mesi, reverse=True)
        self.anno_mese_combo['values'] = ["all"] + anni_mesi_sorted
        
        self.apply_filters()
    
    def apply_filters(self):
        """Applica filtri e sort"""
        self.filter_state['anno_mese'] = self.anno_mese_var.get()
        self.filter_state['genere'] = self.genere_var.get()
        self.filter_state['categoria'] = self.categoria_var.get()
        self.filter_state['disciplina'] = self.disciplina_var.get()
        self.filter_state['search'] = self.search_var.get().lower()
        self.filter_state['sort'] = self.sort_var.get()
        
        # Filtra
        filtered = []
        for slug, data in self.all_races:
            match = True
            # Anno-mese
            if self.filter_state['anno_mese'] != 'all':
                data_str = data.get("data", "")
                if not data_str.startswith(self.filter_state['anno_mese']):
                    match = False
            # Genere
            if match and self.filter_state['genere'] != 'all':
                if data.get('genere') != self.filter_state['genere']:
                    match = False
            # Categoria
            if match and self.filter_state['categoria'] != 'all':
                gara_cats = data.get('categoria', [])
                if isinstance(gara_cats, str):
                    gara_cats = [gara_cats]
                if self.filter_state['categoria'] not in gara_cats:
                    match = False
            # Disciplina
            if match and self.filter_state['disciplina'] != 'all':
                if data.get('disciplina') != self.filter_state['disciplina']:
                    match = False
            # Search
            if match and self.filter_state['search']:
                titolo = data.get('titolo', '').lower()
                luogo = data.get('luogo', '').lower()
                if self.filter_state['search'] not in titolo and self.filter_state['search'] not in luogo:
                    match = False
            
            if match:
                filtered.append((slug, data))
        
        # Sort
        sort_type = self.filter_state['sort']
        if sort_type == 'data-asc':
            filtered.sort(key=lambda x: x[1].get('data', ''))
        elif sort_type == 'data-desc':
            filtered.sort(key=lambda x: x[1].get('data', ''), reverse=True)
        elif sort_type == 'km-asc':
            filtered.sort(key=lambda x: float(x[1].get('distanza_km', 0) or 0))
        elif sort_type == 'km-desc':
            filtered.sort(key=lambda x: float(x[1].get('distanza_km', 0) or 0), reverse=True)
        elif sort_type == 'nome':
            filtered.sort(key=lambda x: x[1].get('titolo', '').lower())
        
        self.filtered_races = filtered
        self.update_listbox()
    
    def update_listbox(self):
        """Aggiorna listbox con gare filtrate"""
        self.race_listbox.delete(0, tk.END)
        self.listbox_index_map = {}  # Reset mapping
        current_index = 0
        
        for slug, data in self.filtered_races:
            tipo = data.get('tipo', '')
            
            # Non mostra le tappe singole se non expanded
            if tipo == 'tappa':
                continue
            
            titolo = data.get('titolo', f'[{slug}]')
            data_gara = data.get('data', '—')
            km = data.get('distanza_km', '—')
            dislivello = data.get('dislivello_m', '—')
            
            if tipo == 'corsa_a_tappe':
                n_tappe = data.get('n_tappe', '?')
                is_expanded = slug in self.expanded_stages
                expand_sym = '▼' if is_expanded else '▶'
                prefix = f'{expand_sym} [⛰ {n_tappe}T]'
            else:
                prefix = '[  ]'
            
            # Formattazione con colonne allineate usando monospace
            line = f"{prefix:10s} {titolo:30s} | {str(data_gara):10s} | {str(km):>7s}km | {str(dislivello):>6s}m"
            self.race_listbox.insert(tk.END, line)
            self.listbox_index_map[current_index] = slug  # Mappa indice -> slug gara
            current_index += 1
            
            # Se la corsa a tappe è expanded, mostra le tappe indentate
            if tipo == 'corsa_a_tappe' and slug in self.expanded_stages:
                for tappa in data.get('tappe', []):
                    t_numero = tappa.get('numero', '?')
                    t_nome = tappa.get('nome', '—')
                    t_data = tappa.get('data', '—')
                    t_km = tappa.get('distanza_km', '—')
                    t_elev = tappa.get('dislivello_m', '—')
                    t_slug = tappa.get('slug', '')  # Slug della tappa
                    t_line = f"  └─ S{t_numero} {t_nome:26s} | {str(t_data):10s} | {str(t_km):>7s}km | {str(t_elev):>6s}m"
                    self.race_listbox.insert(tk.END, t_line)
                    self.listbox_index_map[current_index] = t_slug  # Mappa indice -> slug tappa
                    current_index += 1
    
    def reset_filters(self):
        """Azzera tutti i filtri"""
        self.anno_mese_var.set("all")
        self.genere_var.set("all")
        self.categoria_var.set("all")
        self.disciplina_var.set("all")
        self.search_var.set("")
        self.sort_var.set("data-asc")
        self.apply_filters()
    
    def on_race_select(self, event):
        """Mostra dettagli della gara selezionata"""
        idx = self.race_listbox.curselection()
        if not idx:
            return
        
        # Usa il mapping per trovare lo slug dalla posizione nel listbox
        slug = self.listbox_index_map.get(idx[0])
        if not slug:
            return
        
        # Carica i dati: dalla cache se è gara, dal JSON se è tappa
        data = None
        is_stage = False
        
        # Prova prima a trovare nella cache filtered_races
        for s, d in self.filtered_races:
            if s == slug:
                data = d
                break
        
        # Se non trovato nella cache, potrebbe essere una tappa -> carica dal JSON
        if not data:
            tappa_json_path = GARE_DIR / f"{slug}.json"
            if tappa_json_path.exists():
                try:
                    data = json.loads(tappa_json_path.read_text(encoding='utf-8'))
                    is_stage = True
                except Exception:
                    return
            else:
                return
        
        if not data:
            return
        
        tipo = data.get('tipo', '')
        
        # Mostra i dettagli della gara selezionata nel pannello info
        if tipo == 'corsa_a_tappe':
            tappe_info = ""
            for t in data.get('tappe', []):
                gpx_exists = (GPX_DIR / f"{t.get('slug', '')}-gpx.json").exists()
                gpx_mark = "\u2713" if gpx_exists else "\u2717"
                tappe_info += f"\n  S{t.get('numero','?')}: {t.get('nome','—')} ({t.get('distanza_km','—')}km +{t.get('dislivello_m','—')}m) GPX:{gpx_mark}"

            info = f"""TITOLO:       {data.get('titolo', '—')}
SLUG:         {slug}
TIPO:         ⛰ Corsa a tappe ({data.get('n_tappe','?')} tappe)
DATA INIZIO:  {data.get('data_inizio') or data.get('data', '—')}
DATA FINE:    {data.get('data_fine', '—')}
GENERE:       {data.get('genere', '—')}
CATEGORIE:    {', '.join(data.get('categoria', [])) if isinstance(data.get('categoria'), list) else data.get('categoria', '—')}
DIST TOTALE:  {data.get('distanza_km', '—')} km
D+ TOTALE:    {data.get('dislivello_m', '—')} m
LUOGO:        {data.get('luogo', '—')}
TAPPE:{tappe_info}"""
        elif tipo == 'tappa':
            gpx_file = GPX_DIR / f"{slug}-gpx.json"
            gpx_info = "sì" if gpx_file.exists() else "no"
            velocita = data.get('velocita_media_kmh')
            velocita_str = f"{velocita} km/h" if velocita else "—"
            
            info = f"""TITOLO:       {data.get('titolo', '—')}
SLUG:         {slug}
TIPO:         Tappa (S{data.get('numero_tappa','?')})
CORSA:        {data.get('corsa_a_tappe_titolo', '—')} ({data.get('corsa_a_tappe_slug', '—')})
NOME TAPPA:   {data.get('nome_tappa', '—')}
DATA:         {data.get('data', '—')}
DISCIPLINA:   {data.get('disciplina', '—')}
DISTANZA:     {data.get('distanza_km', '—')} km
DISLIVELLO:   {data.get('dislivello_m', '—')} m
VEL MEDIA:    {velocita_str}
LUOGO:        {data.get('luogo', '—')}
GENERE:       {data.get('genere', '—')}
CATEGORIE:    {', '.join(data.get('categoria', [])) if isinstance(data.get('categoria'), list) else data.get('categoria', '—')}
NOTE:         {(data.get('note', '') or '')[:100]}
GPX FILE:     {gpx_info}"""
        else:
            # Determina quale file GPX verrà usato per questa gara
            gpx_ref  = data.get('gpx_reference', '')
            gpx_slug = gpx_ref if gpx_ref else slug
            gpx_file = GPX_DIR / f"{gpx_slug}-gpx.json"
            if gpx_file.exists():
                if gpx_ref and gpx_ref != slug:
                    gpx_info = f"{gpx_slug}-gpx.json  [da gpx_reference]"
                else:
                    gpx_info = f"{gpx_slug}-gpx.json"
            else:
                gpx_info = "nessuno"

            info = f"""TITOLO:       {data.get('titolo', '—')}
SLUG:         {slug}
DATA:         {data.get('data', '—')}
GENERE:       {data.get('genere', '—')}
CATEGORIE:    {', '.join(data.get('categoria', [])) if isinstance(data.get('categoria'), list) else data.get('categoria', '—')}
{'WORLD TOUR:   ⭐ SÌ' if data.get('wt') else ''}
DISCIPLINA:   {data.get('disciplina', '—')}
DISTANZA:     {data.get('distanza_km', '—')} km
DISLIVELLO:   {data.get('dislivello_m', '—')} m
LUOGO:        {data.get('luogo', '—')}
NOTE:         {(data.get('note', '') or '')[:100]}
GPX FILE:     {gpx_info}"""
        
        self.info_text.config(state="normal")
        self.info_text.delete(1.0, tk.END)
        self.info_text.insert(1.0, info)
        self.info_text.config(state="disabled")
    
    def on_race_double_click(self, event):
        """Doppio click: espandi/collassa corsa a tappe"""
        idx = self.race_listbox.curselection()
        if not idx:
            return
        
        # Usa il mapping per trovare lo slug
        slug = self.listbox_index_map.get(idx[0])
        if not slug:
            return
        
        # Verifica che sia una corsa a tappe (non una tappa singola)
        data = None
        for s, d in self.filtered_races:
            if s == slug and d.get('tipo') == 'corsa_a_tappe':
                data = d
                break
        
        if not data:
            return
        
        # Togglare expand/collapse
        if slug in self.expanded_stages:
            self.expanded_stages.discard(slug)
        else:
            self.expanded_stages.add(slug)
        
        self.update_listbox()
        
        # Re-seleziona lo stesso index (che è rimasto lo stesso nel listbox)
        self.race_listbox.selection_clear(0, tk.END)
        self.race_listbox.selection_set(idx[0])
    
    def add_race(self):
        """Dialogo per scegliere come aggiungere una nuova gara"""
        add_mode_win = tk.Toplevel(self.root)
        add_mode_win.title("Aggiungi nuova gara")
        add_mode_win.geometry("500x280")
        add_mode_win.configure(bg=BG)
        add_mode_win.resizable(False, False)
        
        # Header
        tk.Frame(add_mode_win, bg=ACCENT, height=4).pack(fill="x")
        tk.Label(add_mode_win, text="Come vuoi aggiungere la gara?", font=("Helvetica", 13, "bold"),
                bg=BG, fg=FG, pady=12).pack()
        
        # Description
        tk.Label(add_mode_win, text="Scegli come iniziare:", font=("Helvetica", 10),
                bg=BG, fg="#7a746b", pady=0).pack()
        
        button_frame = tk.Frame(add_mode_win, bg=BG, padx=20, pady=20)
        button_frame.pack(fill="both", expand=True)
        
        def on_load_gpx():
            add_mode_win.destroy()
            gpx_path = filedialog.askopenfilename(
                title='Seleziona file GPX',
                filetypes=[('GPX files', '*.gpx'), ('All files', '*.*')]
            )
            if gpx_path:
                self.new_race_with_gpx(Path(gpx_path))
        
        def on_use_existing():
            add_mode_win.destroy()
            self.new_race_with_existing_gpx()
        
        def on_empty():
            add_mode_win.destroy()
            self.new_race_empty()
        
        # Bottone 1: Carica GPX
        tk.Button(button_frame, text="📁 Carica file GPX", font=("Helvetica", 11, "bold"),
                 bg=ACCENT, fg="white", relief="flat", bd=0, padx=16, pady=12,
                 cursor="hand2", command=on_load_gpx, wraplength=400,
                 justify="left").pack(fill="x", pady=8)
        tk.Label(button_frame, text="Seleziona un file GPX dal computer.\nVerranno estratti automaticamente distanza, dislivello e tracciato.",
                font=("Helvetica", 9), bg=BG, fg="#7a746b", justify="left").pack(fill="x", padx=(0,0))
        
        tk.Frame(button_frame, bg="#d1d5db", height=1).pack(fill="x", pady=12)
        
        # Bottone 2: Usa GPX esistente
        tk.Button(button_frame, text="🔗 Usa GPX di gara precedente", font=("Helvetica", 11, "bold"),
                 bg="#4a7fa5", fg="white", relief="flat", bd=0, padx=16, pady=12,
                 cursor="hand2", command=on_use_existing, wraplength=400,
                 justify="left").pack(fill="x", pady=8)
        tk.Label(button_frame, text="Carica il percorso da una gara che hai già nel database.\nPerfetto se il percorso è identico solo anno diverso.",
                font=("Helvetica", 9), bg=BG, fg="#7a746b", justify="left").pack(fill="x", padx=(0,0))
        
        tk.Frame(button_frame, bg="#d1d5db", height=1).pack(fill="x", pady=12)
        
        # Bottone 3: Niente GPX
        tk.Button(button_frame, text="+  Solo dettagli (niente GPX)", font=("Helvetica", 11, "bold"),
                 bg="#8b8b8b", fg="white", relief="flat", bd=0, padx=16, pady=12,
                 cursor="hand2", command=on_empty, wraplength=400,
                 justify="left").pack(fill="x", pady=8)
        tk.Label(button_frame, text="Compila manualmente i dettagli della gara (titolo, data, categoria, ecc).\nPotrai sempre aggiungere il GPX in seguito.",
                font=("Helvetica", 9), bg=BG, fg="#7a746b", justify="left").pack(fill="x", padx=(0,0))
    
    def new_race_with_gpx(self, gpx_path: Path):
        """Aggiunge gara da file GPX"""
        print(f"[*] Lettura GPX: {gpx_path.name}...")
        gpx_data = parse_gpx(gpx_path)
        
        # Prepara dati iniziali
        new_data = {
            'titolo': gpx_path.stem,
            'race_series': gpx_path.stem,
            'data': date.today().isoformat(),
            'genere': 'Femminile',
            'categoria': ['Junior'],
            'disciplina': 'Strada',
            'giri': 1,
            'velocita_media_kmh': 40,
        }
        
        if gpx_data.get('distanza_km'):
            new_data['distanza_km'] = gpx_data['distanza_km']
        if gpx_data.get('dislivello_m'):
            new_data['dislivello_m'] = gpx_data['dislivello_m']
        if gpx_data.get('gpx_points'):
            new_data['gpx_points'] = gpx_data['gpx_points']
        
        # Reverse geocoding per il luogo
        if gpx_data.get('center_lat') and gpx_data.get('center_lon'):
            lat = gpx_data.get('center_lat')
            lon = gpx_data.get('center_lon')
            luogo = reverse_geocode(lat, lon)
            if luogo:
                new_data['luogo'] = luogo
        
        self.open_add_race_form(new_data, is_new=True)
    
    def new_race_with_existing_gpx(self):
        """Aggiunge gara referenziando un file GPX esistente (da gare-sorgenti/gpx/)"""
        # Scansiona i file GPX disponibili
        existing_races = []
        for gpx_file in sorted(GPX_DIR.glob("*-gpx.json"), reverse=True):
            gpx_slug = gpx_file.stem[:-4]   # rimuove '-gpx'
            # Prova a trovare il titolo dal file dettagli corrispondente
            details_file = GARE_DIR / f"{gpx_slug}.json"
            titolo = gpx_slug
            data_gara = ""
            if details_file.exists():
                try:
                    d = json.loads(details_file.read_text(encoding='utf-8'))
                    titolo = d.get('titolo', gpx_slug)
                    data_gara = d.get('data', '')
                except Exception:
                    pass
            existing_races.append((gpx_slug, titolo, data_gara))

        if not existing_races:
            messagebox.showwarning("Attenzione", "Non ci sono file GPX nel database (cartella gare-sorgenti/gpx/ vuota)")
            return
        
        select_win = tk.Toplevel(self.root)
        select_win.title("Seleziona gara di riferimento")
        select_win.geometry("500x400")
        select_win.configure(bg=BG)
        
        tk.Label(select_win, text="Seleziona la gara da cui copiare il GPX:", 
                font=("Helvetica", 11, "bold"), bg=BG, fg=FG, pady=12).pack()
        
        # Campo di ricerca
        search_frame = tk.Frame(select_win, bg=BG)
        search_frame.pack(fill="x", padx=12, pady=(0, 8))
        
        tk.Label(search_frame, text="🔍 Ricerca:", font=("Helvetica", 9, "bold"),
                bg=BG, fg="#7a746b").pack(side="left", padx=(0, 6))
        
        search_var = tk.StringVar()
        search_entry = tk.Entry(search_frame, textvariable=search_var, font=("Helvetica", 10),
                               bg="white", fg=FG, relief="solid", bd=1)
        search_entry.pack(side="left", fill="x", expand=True)
        search_entry.focus()
        
        list_frame = tk.Frame(select_win, bg="white", relief="solid", bd=1)
        list_frame.pack(fill="both", expand=True, padx=12, pady=12)
        
        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")
        
        race_listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set, bg="white",
                                 selectmode="single", font=("Courier", 9), bd=0)
        race_listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=race_listbox.yview)
        
        # Lista di indici per track quali righe sono visibili after filtering
        displayed_indices = []
        
        def update_listbox(*args):
            """Aggiorna listbox filtrando per il testo di ricerca"""
            nonlocal displayed_indices
            race_listbox.delete(0, tk.END)
            displayed_indices = []
            
            search_text = search_var.get().lower()
            
            for idx, (slug, titolo, data_gara) in enumerate(existing_races):
                if search_text == "" or search_text in titolo.lower() or search_text in slug.lower():
                    race_listbox.insert(tk.END, f"{titolo:30s} | {data_gara}")
                    displayed_indices.append(idx)
        
        # Popola inizialmente e collega il filtro
        update_listbox()
        search_var.trace_add("write", update_listbox)
        
        def on_select():
            sel = race_listbox.curselection()
            if not sel:
                messagebox.showwarning("Attenzione", "Seleziona una gara prima")
                return

            # Recupera il vero indice dalla lista originale
            displayed_idx = sel[0]
            actual_idx = displayed_indices[displayed_idx]
            gpx_slug, titolo_ref, data_gara = existing_races[actual_idx]

            # Carica info dai dettagli se disponibili
            ref_distanza = None
            ref_dislivello = None
            ref_luogo = None
            details_file = GARE_DIR / f"{gpx_slug}.json"
            if details_file.exists():
                try:
                    d = json.loads(details_file.read_text(encoding='utf-8'))
                    ref_distanza  = d.get('distanza_km')
                    ref_dislivello = d.get('dislivello_m')
                    ref_luogo     = d.get('luogo')
                except Exception:
                    pass

            # Crea nuova gara con riferimento GPX
            new_data = {
                'titolo':       titolo_ref,
                'data':         date.today().isoformat(),
                'genere':       'Femminile',
                'categoria':    ['Junior'],
                'disciplina':   'Strada',
                'giri':         1,
                'gpx_reference': gpx_slug,
                'distanza_km':  ref_distanza,
                'dislivello_m': ref_dislivello,
            }
            if ref_luogo:
                new_data['luogo'] = ref_luogo

            select_win.destroy()
            self.open_add_race_form(new_data, is_new=True)
        
        button_frame = tk.Frame(select_win, bg=BG)
        button_frame.pack(fill="x", padx=12, pady=12)
        
        tk.Button(button_frame, text="Seleziona", bg=ACCENT, fg="white", padx=16, pady=6,
                 relief="flat", bd=0, cursor="hand2", command=on_select).pack(side="left", padx=(0, 6))
        tk.Button(button_frame, text="Annulla", bg="#d1d5db", fg=FG, padx=16, pady=6,
                 relief="flat", bd=0, cursor="hand2", command=select_win.destroy).pack(side="left")
    
    def new_race_empty(self):
        """Aggiunge gara senza GPX, solo metadati"""
        new_data = {
            'titolo': '',
            'data': date.today().isoformat(),
            'genere': 'Femminile',
            'categoria': ['Junior'],
            'disciplina': 'Strada',
            'giri': 1,
        }
        
        self.open_add_race_form(new_data, is_new=True)
    
    def open_race_series_selector(self, callback, parent_win=None):
        """Apre una finestra modale per selezionare una serie già inserita
        
        Args:
            callback: funzione da chiamare con la serie selezionata
            parent_win: finestra padre per posizionamento modale
        """
        select_win = tk.Toplevel(parent_win or self.root)
        select_win.title("Seleziona Serie")
        select_win.geometry("500x400")
        select_win.configure(bg=BG)
        select_win.resizable(True, True)
        
        # Header
        tk.Label(select_win, text="Seleziona una serie esistente", font=("Helvetica", 11, "bold"),
                bg=BG, fg=FG, pady=8).pack(fill="x", padx=12)
        
        # Frame ricerca
        search_frame = tk.Frame(select_win, bg=BG)
        search_frame.pack(fill="x", padx=12, pady=(6, 12))
        
        tk.Label(search_frame, text="🔍 Ricerca:", font=("Helvetica", 9, "bold"),
                bg=BG, fg="#7a746b").pack(side="left", padx=(0, 6))
        
        search_var = tk.StringVar()
        search_entry = tk.Entry(search_frame, textvariable=search_var, font=("Helvetica", 10),
                               bg="white", fg=FG, relief="solid", bd=1)
        search_entry.pack(side="left", fill="x", expand=True)
        search_entry.focus()
        
        # Frame listbox
        list_frame = tk.Frame(select_win, bg="white", relief="solid", bd=1)
        list_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        
        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")
        
        series_listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set, bg="white",
                                   selectmode="single", font=("Courier", 10), bd=0)
        series_listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=series_listbox.yview)
        
        # Track indici visibili per filtro
        displayed_indices = []
        
        def update_listbox(*args):
            """Aggiorna listbox filtrando per il testo di ricerca"""
            nonlocal displayed_indices
            series_listbox.delete(0, tk.END)
            displayed_indices = []
            
            search_text = search_var.get().lower()
            all_series = get_all_race_series()
            
            for idx, series in enumerate(all_series):
                if search_text == "" or search_text in series.lower():
                    series_listbox.insert(tk.END, series)
                    displayed_indices.append(idx)
        
        # Popola inizialmente
        update_listbox()
        search_var.trace_add("write", update_listbox)
        
        def on_double_click(event):
            """Doppio click per selezionare"""
            sel = series_listbox.curselection()
            if sel:
                on_select()
        
        series_listbox.bind("<Double-Button-1>", on_double_click)
        
        def on_select():
            sel = series_listbox.curselection()
            if not sel:
                messagebox.showwarning("Attenzione", "Seleziona una serie prima")
                return
            
            # Recupera la serie selezionata
            all_series = get_all_race_series()
            displayed_idx = sel[0]
            actual_idx = displayed_indices[displayed_idx]
            selected_series = all_series[actual_idx]
            
            # Chiama la callback con la serie selezionata
            callback(selected_series)
            select_win.destroy()
        
        # Frame bottoni
        button_frame = tk.Frame(select_win, bg=BG)
        button_frame.pack(fill="x", padx=12, pady=12)
        
        tk.Button(button_frame, text="Seleziona", bg=ACCENT, fg="white", padx=16, pady=6,
                 relief="flat", bd=0, cursor="hand2", command=on_select).pack(side="left", padx=(0, 6))
        tk.Button(button_frame, text="Annulla", bg="#d1d5db", fg=FG, padx=16, pady=6,
                 relief="flat", bd=0, cursor="hand2", command=select_win.destroy).pack(side="left")
    
    def open_add_race_form(self, initial_data: dict, is_new: bool = False, original_slug: str = ""):
        """Apre il form per compilare/modificare i dettagli della gara"""
        edit_win = tk.Toplevel(self.root)
        edit_win.title("Aggiungi gara" if is_new else f"Modifica: {initial_data.get('titolo', '')}")
        edit_win.geometry("500x850")
        edit_win.configure(bg=BG)
        
        # Crea copia per modifiche
        data = initial_data.copy()
        
        # Calcolo valori raw (per singolo giro)
        giri_iniziali = max(1, int(data.get('giri', 1)))
        km_iniziale = float(data.get('distanza_km', 0)) or 0
        dislivello_iniziale = float(data.get('dislivello_m', 0)) or 0
        km_raw = km_iniziale / giri_iniziali if giri_iniziali > 0 else 0
        dislivello_raw = dislivello_iniziale / giri_iniziali if giri_iniziali > 0 else 0
        
        # Ottieni lista dei file GPX disponibili per il riferimento
        gpx_files_list = sorted(GPX_DIR.glob("*-gpx.json"))
        gpx_slugs = []
        for gpx_f in gpx_files_list:
            gs = gpx_f.stem[:-4]  # rimuove '-gpx'
            gpx_slugs.append(gs)
        opzioni_gare = ["[GPX Caricato]"] + [f"{gs} ({gs}-gpx.json)" for gs in gpx_slugs]
        opzioni_gare_vals = [""] + gpx_slugs
        
        fields = [
            ("slug", "Slug", "entry"),
            ("titolo", "Titolo", "entry"),
            ("race_series", "Serie", "entry"),
            ("data", "Data (AAAA-MM-GG)", "date_with_calendar"),
            ("luogo", "Luogo", "entry"),
            ("giri", "Giri del circuito", "spinner"),
            ("distanza_km", "Distanza (km)", "entry"),
            ("dislivello_m", "Dislivello (m)", "entry"),
            ("velocita_media_kmh", "Velocità media prevista (km/h)", "entry"),
            ("genere", "Genere", "combo", GENERI),
            ("categoria", "Categorie", "categoria_checkboxes", CATEGORIE),
            ("disciplina", "Disciplina", "combo", DISCIPLINE),
            ("wt", "World Tour (WT)", "checkbox"),
            ("gpx_reference", "GPX di riferimento (slug)", "combo_gare", opzioni_gare, opzioni_gare_vals),
        ]
        
        entries = {}
        
        for i, field_info in enumerate(fields):
            key = field_info[0]
            label = field_info[1]
            widget_type = field_info[2]
            
            tk.Label(edit_win, text=label, font=("Helvetica", 10, "bold"), bg=BG).grid(
                row=i, column=0, sticky="w", padx=12, pady=6)
            
            if widget_type == "spinner":
                var = tk.IntVar(value=data.get(key, 1))
                spinner = tk.Spinbox(edit_win, from_=1, to=50, textvariable=var,
                                   font=("Helvetica", 10), width=10)
                spinner.grid(row=i, column=1, sticky="w", padx=12, pady=6)
                entries[key] = var
                
                def on_giri_change(*args, km_raw=km_raw, dislivello_raw=dislivello_raw, entries=entries):
                    try:
                        giri = int(entries['giri'].get())
                        km_new = round(km_raw * giri, 2)
                        dislivello_new = round(dislivello_raw * giri)
                        entries['distanza_km'].delete(0, tk.END)
                        entries['distanza_km'].insert(0, str(km_new))
                        entries['dislivello_m'].delete(0, tk.END)
                        entries['dislivello_m'].insert(0, str(dislivello_new))
                    except:
                        pass
                
                var.trace_add("write", on_giri_change)
                
            elif widget_type == "combo_gare":
                opzioni_labels = field_info[3]
                var = tk.StringVar(value=data.get(key, "") or "")
                combo = tk.OptionMenu(edit_win, var, *opzioni_labels)
                combo.config(width=40)
                combo.grid(row=i, column=1, sticky="ew", padx=12, pady=6)
                entries[key] = var
                
            elif widget_type == "combo":
                options = field_info[3]
                var = tk.StringVar(value=data.get(key, ""))
                combo = tk.OptionMenu(edit_win, var, *options)
                combo.config(width=40)
                combo.grid(row=i, column=1, sticky="ew", padx=12, pady=6)
                entries[key] = var
            
            elif widget_type == "categoria_checkboxes":
                options = field_info[3]
                current_cats = data.get(key, [])
                if isinstance(current_cats, str):
                    current_cats = [current_cats] if current_cats else []
                
                cat_frame = tk.Frame(edit_win, bg=BG)
                cat_frame.grid(row=i, column=1, sticky="ew", padx=12, pady=6)
                
                cat_vars = {}
                for cat in options:
                    var = tk.BooleanVar(value=cat in current_cats)
                    cb = tk.Checkbutton(cat_frame, text=cat, variable=var, bg=BG, font=("Helvetica", 9))
                    cb.pack(side="left", padx=(0, 12))
                    cat_vars[cat] = var
                
                entries[key] = cat_vars
            
            elif widget_type == "checkbox":
                var = tk.BooleanVar(value=bool(data.get(key, False)))
                cb = tk.Checkbutton(edit_win, text="", variable=var, bg=BG, font=("Helvetica", 10))
                cb.grid(row=i, column=1, sticky="w", padx=12, pady=6)
                entries[key] = var
            
            elif widget_type == "date_with_calendar":
                # Entry data + bottone calendario popup
                from datetime import date as date_cls
                import calendar as cal_mod
                
                f_row = tk.Frame(edit_win, bg=BG)
                f_row.grid(row=i, column=1, sticky="ew", padx=12, pady=6)
                f_row.grid_columnconfigure(0, weight=1)
                
                date_entry = tk.Entry(f_row, font=("Helvetica", 10), fg=FG, relief="solid", bd=1)
                date_entry.grid(row=0, column=0, sticky="ew")
                date_entry.insert(0, str(data.get(key, "") or ""))
                
                def open_cal(de=date_entry, parent=edit_win):
                    # Leggi data iniziale
                    try:
                        parts = de.get().split("-")
                        cur_year, cur_month = int(parts[0]), int(parts[1])
                    except Exception:
                        today = date_cls.today()
                        cur_year, cur_month = today.year, today.month
                    
                    top = tk.Toplevel(parent)
                    top.title("Seleziona data")
                    top.resizable(False, False)
                    top.attributes("-topmost", True)
                    top.configure(bg=BG)
                    top.grab_set()
                    
                    state = {"year": cur_year, "month": cur_month}
                    
                    # Header navigazione
                    nav = tk.Frame(top, bg=BG)
                    nav.pack(fill="x", padx=10, pady=(10,4))
                    
                    lbl_month = tk.Label(nav, text="", font=("Helvetica", 11, "bold"),
                                        bg=BG, fg=FG, width=16)
                    lbl_month.pack(side="left", expand=True)
                    
                    def prev_month():
                        if state["month"] == 1:
                            state["month"] = 12; state["year"] -= 1
                        else:
                            state["month"] -= 1
                        refresh()
                    
                    def next_month():
                        if state["month"] == 12:
                            state["month"] = 1; state["year"] += 1
                        else:
                            state["month"] += 1
                        refresh()
                    
                    tk.Button(nav, text="◀", font=("Helvetica", 10), bg=BG, fg=FG,
                             relief="flat", bd=0, cursor="hand2",
                             command=prev_month).pack(side="left")
                    tk.Button(nav, text="▶", font=("Helvetica", 10), bg=BG, fg=FG,
                             relief="flat", bd=0, cursor="hand2",
                             command=next_month).pack(side="right")
                    
                    # Griglia giorni
                    grid_frame = tk.Frame(top, bg=BG)
                    grid_frame.pack(padx=10, pady=(0,10))
                    
                    GIORNI = ["Lu", "Ma", "Me", "Gi", "Ve", "Sa", "Do"]
                    for col, g in enumerate(GIORNI):
                        tk.Label(grid_frame, text=g, font=("Helvetica", 9, "bold"),
                                bg=BG, fg="#7a746b", width=3).grid(row=0, column=col, pady=(0,4))
                    
                    day_buttons = []
                    
                    def refresh():
                        for btn in day_buttons:
                            btn.destroy()
                        day_buttons.clear()
                        
                        y, m = state["year"], state["month"]
                        lbl_month.config(text=f"{cal_mod.month_name[m]} {y}")
                        
                        first_wd = cal_mod.weekday(y, m, 1)
                        days_in_month = cal_mod.monthrange(y, m)[1]
                        today = date_cls.today()
                        
                        cell = 0
                        for blank in range(first_wd):
                            tk.Label(grid_frame, text="", bg=BG, width=3).grid(
                                row=1 + cell // 7, column=cell % 7)
                            cell += 1
                        
                        for day in range(1, days_in_month + 1):
                            d = day
                            is_today = (y == today.year and m == today.month and d == today.day)
                            bg_col = ACCENT if is_today else BG
                            fg_col = "white" if is_today else FG
                            
                            btn = tk.Button(
                                grid_frame, text=str(d), font=("Helvetica", 10),
                                bg=bg_col, fg=fg_col, relief="flat", bd=0,
                                width=3, cursor="hand2",
                                activebackground=ACCENT, activeforeground="white",
                            )
                            btn.config(command=lambda dd=d: select_day(dd))
                            btn.grid(row=1 + cell // 7, column=cell % 7, pady=1)
                            day_buttons.append(btn)
                            cell += 1
                    
                    def select_day(day):
                        chosen = f"{state['year']:04d}-{state['month']:02d}-{day:02d}"
                        de.delete(0, tk.END)
                        de.insert(0, chosen)
                        top.destroy()
                    
                    refresh()
                
                tk.Button(f_row, text="📅", font=("Helvetica", 11), bg=BG, fg=FG,
                         relief="flat", bd=0, cursor="hand2",
                         command=open_cal).grid(row=0, column=1, padx=(4,0))
                
                entries[key] = date_entry
            
            else:
                # Caso speciale per race_series: entry + bottone per selezionare da lista
                if key == "race_series":
                    f_row = tk.Frame(edit_win, bg=BG)
                    f_row.grid(row=i, column=1, sticky="ew", padx=12, pady=6)
                    f_row.grid_columnconfigure(0, weight=1)
                    
                    series_entry = tk.Entry(f_row, font=("Helvetica", 10), fg=FG, relief="solid", bd=1)
                    series_entry.grid(row=0, column=0, sticky="ew")
                    series_entry.insert(0, str(data.get(key, "") or ""))
                    
                    def open_series_selector(series_entry=series_entry, parent=edit_win):
                        """Callback per il bottone di selezione serie"""
                        def on_series_selected(selected_series):
                            series_entry.delete(0, tk.END)
                            series_entry.insert(0, selected_series)
                        
                        self.open_race_series_selector(on_series_selected, parent)
                    
                    tk.Button(f_row, text="📋", font=("Helvetica", 11), bg=BG, fg=FG,
                             relief="flat", bd=0, cursor="hand2",
                             command=open_series_selector).grid(row=0, column=1, padx=(4,0))
                    
                    entries[key] = series_entry
                else:
                    entry = tk.Entry(edit_win, width=35, font=("Helvetica", 10))
                    entry.insert(0, str(data.get(key, "") or ""))
                    entry.grid(row=i, column=1, sticky="ew", padx=12, pady=6)
                    entries[key] = entry
        
        # Auto-slug: quando cambia titolo o data, aggiorna slug automaticamente
        slug_manual = tk.BooleanVar(value=False)
        
        def update_slug(*args):
            """Aggiorna slug automaticamente dal titolo, data, genere e categoria se non modificato manualmente"""
            if not slug_manual.get():
                try:
                    titolo = entries['titolo'].get().strip()
                    data_str = entries['data'].get().strip()
                    year = data_str.split('-')[0] if data_str and len(data_str) >= 4 else "2026"
                    
                    # Aggiungi il codice categoria allo slug
                    genere = entries['genere'].get() if isinstance(entries['genere'], tk.StringVar) else ""
                    
                    # Estrai TUTTE le categorie selezionate e ordinale
                    categoria_order = ['Allievi', 'Junior', 'U23', 'Elite']
                    categorie_selezionate = []
                    if isinstance(entries['categoria'], dict):
                        for cat in categoria_order:
                            if cat in entries['categoria'] and entries['categoria'][cat].get():
                                categorie_selezionate.append(cat)
                    
                    # Genera i codici categoria per ogni categoria selezionata
                    cat_codes = []
                    for categoria in categorie_selezionate:
                        cat_code = categoria_code(genere, categoria)
                        if cat_code:
                            cat_codes.append(cat_code)
                    
                    if titolo:
                        new_auto_slug = slugify(titolo) + f"-{year}"
                        if cat_codes:
                            new_auto_slug += f"-{'-'.join(cat_codes)}"
                    else:
                        new_auto_slug = ""
                    
                    entries['slug'].delete(0, tk.END)
                    entries['slug'].insert(0, new_auto_slug)
                except:
                    pass
        
        # Collega i binding SOLO per gare nuove
        if is_new:
            # Collega i binding per titolo e data
            if isinstance(entries['titolo'], tk.Entry):
                entries['titolo'].bind("<KeyRelease>", update_slug)
            
            if isinstance(entries['data'], tk.Entry):
                entries['data'].bind("<KeyRelease>", update_slug)
                entries['data'].bind("<FocusOut>", update_slug)
            
            # Collega binding per genere (StringVar)
            if isinstance(entries['genere'], tk.StringVar):
                entries['genere'].trace_add("write", update_slug)
            
            # Collega binding per categoria (dict di BooleanVar)
            if isinstance(entries['categoria'], dict):
                for cat, var in entries['categoria'].items():
                    var.trace_add("write", update_slug)
        
        # Quando l'utente modifica lo slug manualmente, disabilita l'auto-update
        if isinstance(entries['slug'], tk.Entry):
            def on_slug_edit(event):
                slug_manual.set(True)
            entries['slug'].bind("<KeyPress>", on_slug_edit)
        
        # Genera slug iniziale SOLO per gare nuove
        if is_new:
            update_slug()
        
        # ── Gestione Tipo pista: azzera km e dislivello ────────────────────────
        # Salva i valori RAW di backup (per singolo giro) per il ripristino
        km_dislivello_backup = {
            'distanza_km': km_raw,
            'dislivello_m': dislivello_raw,
        }
        
        def on_disciplina_change(*args):
            """Quando disciplina cambia: se è Tipo pista, svuota km e dislivello"""
            disciplina_val = entries['disciplina'].get()
            
            if disciplina_val == "Tipo pista":
                # Salva i valori RAW prima di cancellare (per ripristino successivo)
                try:
                    km_attuale = float(entries['distanza_km'].get()) if entries['distanza_km'].get() else 0
                    dislivello_attuale = float(entries['dislivello_m'].get()) if entries['dislivello_m'].get() else 0
                    giri_correnti = int(entries['giri'].get()) if entries['giri'].get() else 1
                    if giri_correnti > 0:
                        km_dislivello_backup['distanza_km'] = round(km_attuale / giri_correnti, 2)
                        km_dislivello_backup['dislivello_m'] = round(dislivello_attuale / giri_correnti)
                except:
                    pass
                
                # Svuota i campi
                entries['distanza_km'].delete(0, tk.END)
                entries['dislivello_m'].delete(0, tk.END)
            else:
                # Se torna a un'altra disciplina e c'è un backup, ripristina moltiplicando per i giri correnti
                try:
                    giri_correnti = int(entries['giri'].get()) if entries['giri'].get() else 1
                    if giri_correnti < 1:
                        giri_correnti = 1
                except:
                    giri_correnti = 1
                
                if km_dislivello_backup['distanza_km'] is not None:
                    km_ripristinato = round(km_dislivello_backup['distanza_km'] * giri_correnti, 2)
                    entries['distanza_km'].delete(0, tk.END)
                    entries['distanza_km'].insert(0, str(km_ripristinato))
                if km_dislivello_backup['dislivello_m'] is not None:
                    dislivello_ripristinato = round(km_dislivello_backup['dislivello_m'] * giri_correnti)
                    entries['dislivello_m'].delete(0, tk.END)
                    entries['dislivello_m'].insert(0, str(dislivello_ripristinato))
        
        # Se la disciplina è una StringVar, collega il binding
        if isinstance(entries['disciplina'], tk.StringVar):
            entries['disciplina'].trace_add("write", on_disciplina_change)
        
        def load_gpx_file():
            """Carica file GPX e aggiorna i dati della gara"""
            gpx_file = filedialog.askopenfilename(
                title="Seleziona file GPX",
                filetypes=[('GPX files', '*.gpx'), ('All files', '*.*')],
                parent=edit_win
            )
            
            if not gpx_file:
                return
            
            try:
                gpx_data = parse_gpx(Path(gpx_file))
                
                if not gpx_data.get('gpx_points'):
                    messagebox.showwarning("Attenzione", "Il file GPX non contiene dati validi")
                    return
                
                # Aggiorna i dati con le informazioni dal GPX
                if gpx_data.get('distanza_km'):
                    data['distanza_km'] = gpx_data['distanza_km']
                    entries['distanza_km'].delete(0, tk.END)
                    entries['distanza_km'].insert(0, str(gpx_data['distanza_km']))
                
                if gpx_data.get('dislivello_m'):
                    data['dislivello_m'] = gpx_data['dislivello_m']
                    entries['dislivello_m'].delete(0, tk.END)
                    entries['dislivello_m'].insert(0, str(gpx_data['dislivello_m']))
                
                # Salva i punti GPX nei dati (save_race() li sposterà nel file separato)
                data['gpx_points'] = gpx_data['gpx_points']
                # Pulisci gpx_reference se si carica un gpx proprio
                if 'gpx_reference' in data:
                    del data['gpx_reference']
                # Aggiorna anche il widget del combo GPX reference
                if isinstance(entries.get('gpx_reference'), tk.StringVar):
                    entries['gpx_reference'].set(opzioni_gare[0])  # Imposta a "[GPX Caricato]"
                
                # Reverse geocoding per il luogo (se non è stato ancora impostato)
                if gpx_data.get('center_lat') and gpx_data.get('center_lon'):
                    if not entries['luogo'].get().strip():
                        lat = gpx_data.get('center_lat')
                        lon = gpx_data.get('center_lon')
                        luogo = reverse_geocode(lat, lon)
                        if luogo:
                            data['luogo'] = luogo
                            entries['luogo'].delete(0, tk.END)
                            entries['luogo'].insert(0, luogo)
                
                messagebox.showinfo("Successo", "GPX caricato con successo!\nDistanza e dislivello sono stati aggiornati.")
                
                # Porta la finestra di modifica in primo piano
                edit_win.lift()
                edit_win.attributes("-topmost", True)
                edit_win.after(500, lambda: edit_win.attributes("-topmost", False))
            
            except Exception as e:
                messagebox.showerror("Errore", f"Errore nel caricamento del GPX:\n{str(e)}")
        
        def save_changes():
            new_slug = None
            
            for key, widget in entries.items():
                if key == "categoria":
                    # Estrai categorie selezionate dai checkbutton
                    if isinstance(widget, dict):
                        selected_cats = [cat for cat, var in widget.items() if var.get()]
                        data[key] = selected_cats
                    continue
                
                if key == "wt":
                    # Estrai valore booleano dal checkbox WT
                    data[key] = widget.get() if hasattr(widget, 'get') else bool(widget)
                    # Se è False, non lo salvare nel JSON (per ridurre dimensione)
                    if not data[key] and key in data:
                        del data[key]
                    continue
                
                if key == "gpx_reference":
                    current_val = widget.get()
                    if not current_val or current_val == "[GPX Caricato]":
                        if key in data:
                            del data[key]
                    else:
                        # Formato: "gpx-slug (gpx-slug-gpx.json)" → prendi la parte prima del spazio
                        gpx_ref_slug = current_val.split(" (")[0].strip()
                        if gpx_ref_slug:
                            data[key] = gpx_ref_slug
                    continue
                
                val = widget.get() if hasattr(widget, 'get') else widget
                
                if key == "slug":
                    new_slug = val
                    data[key] = val
                    continue
                
                if key in ("distanza_km", "dislivello_m", "giri", "velocita_media_kmh"):
                    try:
                        if key == "giri":
                            val = int(val) if val else 1
                        else:
                            val = float(val) if val else None
                    except:
                        val = None
                elif key == "race_series":
                    # Rendi case-insensitive: converti a minuscolo
                    val = val.lower() if val else ""
                               
                data[key] = val
            
            # Se è Tipo pista, forza distanza_km e dislivello_m a None (non conteggiati)
            if data.get('disciplina') == 'Tipo pista':
                data['distanza_km'] = None
                data['dislivello_m'] = None
            
            # Se è nuova gara, genera slug automaticamente
            if is_new and (not new_slug or new_slug.strip() == ""):
                year = data.get('data', '').split('-')[0] if data.get('data') else "2026"
                new_slug = slugify(data.get('titolo', '')) + f"-{year}"
                data['slug'] = new_slug
            elif new_slug:
                data['slug'] = new_slug
            
            # Validazioni
            if not data.get('titolo', '').strip():
                messagebox.showerror("Errore", "Titolo obbligatorio")
                return
            
            if not data.get('race_series', '').strip():
                messagebox.showerror("Errore", "Serie obbligatoria")
                return
            
            if not data.get('slug', '').strip():
                messagebox.showerror("Errore", "Slug obbligatorio")
                return
            
            # Salva
            save_race(data.get('slug'), data)
            messagebox.showinfo("Salvato", "Gara modificata con successo!")
            self.refresh_list()
            edit_win.destroy()
        
        row_button = len(fields)
        button_frame = tk.Frame(edit_win, bg=BG)
        button_frame.grid(row=row_button, column=0, columnspan=2, sticky="ew", padx=12, pady=12)
        
        def regenerate_slug():
            """Forza la rigenerazione dello slug automatico"""
            slug_manual.set(False)
            update_slug()
        
        tk.Button(button_frame, text="📁 Carica GPX", bg="#8b5cf6", fg="white", padx=12, pady=6,
                 relief="flat", bd=0, cursor="hand2", command=load_gpx_file).pack(side="left", padx=(0, 6))
        tk.Button(button_frame, text="🔧 Rigenera slug", bg="#06b6d4", fg="white", padx=12, pady=6,
                 relief="flat", bd=0, cursor="hand2", command=regenerate_slug).pack(side="left", padx=(0, 6))
        tk.Button(button_frame, text="Salva", bg=ACCENT, fg="white", padx=16, pady=6,
                 relief="flat", bd=0, cursor="hand2", command=save_changes).pack(side="left", padx=(0, 6))
        tk.Button(button_frame, text="Annulla", bg="#d1d5db", fg=FG, padx=16, pady=6,
                 relief="flat", bd=0, cursor="hand2", command=edit_win.destroy).pack(side="left")
        
        edit_win.columnconfigure(1, weight=1)
    
    def add_stage_race(self):
        """Apre il form per creare una nuova corsa a tappe"""
        self.open_stage_race_form(initial_data=None, is_new=True)

    def open_stage_race_form(self, initial_data: dict = None, is_new: bool = True):
        """Form completo per creare/modificare una corsa a tappe"""
        win = tk.Toplevel(self.root)
        win.title("Nuova corsa a tappe" if is_new else f"Modifica: {(initial_data or {}).get('titolo', '')}")
        win.configure(bg=BG)

        # ── dati interni ───────────────────────────────────────────────────
        data = (initial_data or {}).copy()
        # Lista tappe: ognuna è un dict con chiavi:
        #   numero, nome, slug_tappa, data, disciplina, distanza_km, dislivello_m, luogo, velocita_media_kmh, gpx_points
        stages: list[dict] = []
        if data.get('tappe'):
            for t in data['tappe']:
                stage_slug = t.get('slug', '')
                
                # Carica i dati completi della tappa dal file JSON separato se esiste
                tappa_completa = {}
                tappa_json_path = GARE_DIR / f"{stage_slug}.json"
                if tappa_json_path.exists():
                    try:
                        tappa_completa = json.loads(tappa_json_path.read_text(encoding='utf-8'))
                    except Exception:
                        pass
                
                # ricarica i gpx_points dal file, se esiste
                gpx_pts = None
                gpx_path = GPX_DIR / f"{stage_slug}-gpx.json"
                if gpx_path.exists():
                    try:
                        gd = json.loads(gpx_path.read_text(encoding='utf-8'))
                        gpx_pts = gd.get('gpx_points')
                    except Exception:
                        pass
                _giri = max(1, t.get('giri', 1))
                _km   = t.get('distanza_km')
                _elev = t.get('dislivello_m')
                stages.append({
                    'numero':       t.get('numero', len(stages) + 1),
                    'nome':         t.get('nome', ''),
                    'slug_tappa':   stage_slug,
                    'data':         t.get('data', ''),
                    'disciplina':   t.get('disciplina', 'Strada'),
                    'giri':         _giri,
                    'distanza_km':  _km,
                    'dislivello_m': _elev,
                    'luogo':        tappa_completa.get('luogo') or t.get('luogo'),
                    'velocita_media_kmh': tappa_completa.get('velocita_media_kmh') or t.get('velocita_media_kmh'),
                    'gpx_points':   gpx_pts,
                    '_base_km':     round(_km / _giri, 4) if _km else None,
                    '_base_elev':   round(_elev / _giri) if _elev else None,
                })

        selected_stage = [None]  # indice tappa selezionata
        orphaned_stage_slugs: set[str] = set()  # slug di tappe da eliminare dal disco al salvataggio

        # ── layout principale con Canvas scrollabile ────────────────────────
        main_frame = tk.Frame(win, bg=BG)
        main_frame.pack(fill="both", expand=True)

        canvas = tk.Canvas(main_frame, bg=BG, highlightthickness=0)
        scrollbar = tk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        scroll_frame = tk.Frame(canvas, bg=BG)
        sw_id = canvas.create_window((0, 0), window=scroll_frame, anchor="nw")

        def _on_frame_configure(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        def _on_canvas_configure(e):
            canvas.itemconfig(sw_id, width=e.width)

        scroll_frame.bind("<Configure>", _on_frame_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        win.bind("<Destroy>", lambda e: canvas.unbind_all("<MouseWheel>"))

        # ── Sezione 1: dati corsa principale ──────────────────────────────
        tk.Frame(scroll_frame, bg=ACCENT, height=4).pack(fill="x")
        tk.Label(scroll_frame, text="\u26f0  Corsa a Tappe", font=("Helvetica", 14, "bold"),
                 bg=BG, fg=FG, pady=8).pack(anchor="w", padx=14)

        race_frame = tk.LabelFrame(scroll_frame, text="Dati corsa principale",
                                   bg=BG, fg=FG, font=("Helvetica", 10, "bold"),
                                   padx=10, pady=8)
        race_frame.pack(fill="x", padx=14, pady=(0, 8))
        race_frame.columnconfigure(1, weight=1)

        race_entries = {}

        import calendar as cal_mod

        def _open_calendar(parent_win, sv, min_date=None, max_date=None, reference_date=None):
            """Popup calendario. sv è un tk.StringVar che contiene la data AAAA-MM-GG.
            min_date e max_date sono stringhe AAAA-MM-GG per limitare le date selezionabili.
            reference_date è una stringa AAAA-MM-GG per impostare il mese/anno iniziale (invece di today)."""
            try:
                parts = sv.get().split("-")
                cur_year, cur_month = int(parts[0]), int(parts[1])
            except Exception:
                # Se reference_date è fornito, usa quello come punto di partenza
                if reference_date:
                    try:
                        p = reference_date.split("-")
                        cur_year, cur_month = int(p[0]), int(p[1])
                    except:
                        _td = date.today()
                        cur_year, cur_month = _td.year, _td.month
                else:
                    _td = date.today()
                    cur_year, cur_month = _td.year, _td.month
            
            # Converti min_date e max_date in date objects
            min_d = None
            max_d = None
            if min_date:
                try:
                    p = min_date.split("-")
                    min_d = date(int(p[0]), int(p[1]), int(p[2]))
                except:
                    pass
            if max_date:
                try:
                    p = max_date.split("-")
                    max_d = date(int(p[0]), int(p[1]), int(p[2]))
                except:
                    pass
            
            top = tk.Toplevel(parent_win)
            top.title("Seleziona data")
            top.resizable(False, False)
            top.attributes("-topmost", True)
            top.configure(bg=BG)
            top.grab_set()
            state = {"year": cur_year, "month": cur_month}
            
            # ── Navigazione mese/anno con controllo anno ──
            nav = tk.Frame(top, bg=BG)
            nav.pack(fill="x", padx=10, pady=(10, 4))
            
            # Bottone anno (cliccabile per scegliere l'anno)
            lbl_mese = tk.Label(nav, text="", font=("Helvetica", 11, "bold"),
                                bg=BG, fg=FG, width=18, cursor="hand2")
            lbl_mese.pack(side="left", expand=True)
            
            def open_year_picker():
                """Popup per scegliere l'anno rapidamente"""
                year_win = tk.Toplevel(top)
                year_win.title("Scegli anno")
                year_win.resizable(False, False)
                year_win.attributes("-topmost", True)
                year_win.configure(bg=BG)
                year_win.grab_set()
                
                # Range di anni: da 2020 a 2035
                years = list(range(2020, 2036))
                
                tk.Label(year_win, text="Seleziona anno:", font=("Helvetica", 10, "bold"),
                        bg=BG, fg=FG, pady=8).pack()
                
                buttons_frame = tk.Frame(year_win, bg=BG, padx=10)
                buttons_frame.pack(pady=8)
                
                for i, y in enumerate(years):
                    col = i % 4
                    row = i // 4
                    bg_y = ACCENT if y == state["year"] else BG
                    fg_y = "white" if y == state["year"] else FG
                    
                    def _select_year(yy=y):
                        state["year"] = yy
                        year_win.destroy()
                        _cal_ref()
                    
                    tk.Button(buttons_frame, text=str(y), font=("Helvetica", 9),
                             bg=bg_y, fg=fg_y, relief="solid", bd=1,
                             width=5, cursor="hand2",
                             activebackground=ACCENT, activeforeground="white",
                             command=_select_year).grid(row=row, column=col, padx=2, pady=2)
            
            lbl_mese.bind("<Button-1>", lambda e: open_year_picker())
            
            def prev_m():
                if state["month"] == 1: state["month"] = 12; state["year"] -= 1
                else: state["month"] -= 1
                _cal_ref()
            
            def next_m():
                if state["month"] == 12: state["month"] = 1; state["year"] += 1
                else: state["month"] += 1
                _cal_ref()
            
            tk.Button(nav, text="◀◀", font=("Helvetica", 9), bg=BG, fg=FG,
                      relief="flat", bd=0, cursor="hand2",
                      command=lambda: (state.update({"year": state["year"] - 1}), _cal_ref())).pack(side="left", padx=2)
            tk.Button(nav, text="◄", font=("Helvetica", 10), bg=BG, fg=FG,
                      relief="flat", bd=0, cursor="hand2", command=prev_m).pack(side="left", padx=2)
            tk.Button(nav, text="►", font=("Helvetica", 10), bg=BG, fg=FG,
                      relief="flat", bd=0, cursor="hand2", command=next_m).pack(side="right", padx=2)
            tk.Button(nav, text="►►", font=("Helvetica", 9), bg=BG, fg=FG,
                      relief="flat", bd=0, cursor="hand2",
                      command=lambda: (state.update({"year": state["year"] + 1}), _cal_ref())).pack(side="right", padx=2)
            
            grid_f = tk.Frame(top, bg=BG)
            grid_f.pack(padx=10, pady=(0, 10))
            for col, g in enumerate(["Lu", "Ma", "Me", "Gi", "Ve", "Sa", "Do"]):
                tk.Label(grid_f, text=g, font=("Helvetica", 9, "bold"),
                         bg=BG, fg="#7a746b", width=3).grid(row=0, column=col, pady=(0, 4))
            day_btns = []
            
            def _cal_ref():
                for b in day_btns: b.destroy()
                day_btns.clear()
                y, m = state["year"], state["month"]
                lbl_mese.config(text=f"{cal_mod.month_name[m]} {y}")
                first_wd = cal_mod.weekday(y, m, 1)
                n_days = cal_mod.monthrange(y, m)[1]
                _today = date.today()
                cell = 0
                for _ in range(first_wd):
                    tk.Label(grid_f, text="", bg=BG, width=3).grid(
                        row=1 + cell // 7, column=cell % 7)
                    cell += 1
                for d in range(1, n_days + 1):
                    curr_date = date(y, m, d)
                    is_today = (y == _today.year and m == _today.month and d == _today.day)
                    
                    # Verifica se la data è nel range (se specificato)
                    is_in_range = True
                    if min_d and curr_date < min_d:
                        is_in_range = False
                    if max_d and curr_date > max_d:
                        is_in_range = False
                    
                    # Colore e stato del bottone
                    if is_in_range:
                        bg_color = ACCENT if is_today else BG
                        fg_color = "white" if is_today else FG
                        state_active = "normal"
                        cursor = "hand2"
                    else:
                        # Disabilitato: grigio scuro con forte contrasto
                        bg_color = "#d0d0d0"
                        fg_color = "#555555"
                        state_active = "disabled"
                        cursor = "arrow"
                    
                    btn = tk.Button(
                        grid_f, text=str(d), font=("Helvetica", 10),
                        bg=bg_color, fg=fg_color,
                        relief="solid", bd=1, width=3, cursor=cursor,
                        activebackground=ACCENT if is_in_range else "#c8c8c8",
                        activeforeground="white" if is_in_range else "#333333",
                        state=state_active,
                    )
                    if is_in_range:
                        btn.config(command=lambda dd=d: _pick(dd))
                    btn.grid(row=1 + cell // 7, column=cell % 7, pady=1)
                    day_btns.append(btn)
                    cell += 1
            
            def _pick(day):
                sv.set(f"{state['year']:04d}-{state['month']:02d}-{day:02d}")
                top.destroy()
            
            _cal_ref()

        def _race_date_field(parent, row, key, label, default=""):
            """Come _race_field ma con bottone 📅 per aprire il calendario."""
            tk.Label(parent, text=label, font=("Helvetica", 9, "bold"), bg=BG, fg=FG).grid(
                row=row, column=0, sticky="w", padx=(0, 8), pady=4)
            f = tk.Frame(parent, bg=BG)
            f.grid(row=row, column=1, sticky="ew", pady=4)
            f.columnconfigure(0, weight=1)
            var = tk.StringVar(value=str(data.get(key, default) or default))
            tk.Entry(f, textvariable=var, font=("Helvetica", 10), relief="solid", bd=1).grid(
                row=0, column=0, sticky="ew")
            
            def open_cal():
                # Se è data_fine, usa data_inizio come reference per il mese iniziale
                ref_date = None
                if key == 'data_fine' and 'data_inizio' in race_entries:
                    ref_date = race_entries['data_inizio'].get().strip()
                    if not ref_date:
                        ref_date = None
                _open_calendar(win, var, reference_date=ref_date)
            
            tk.Button(f, text="📅", font=("Helvetica", 11), bg=BG, fg=FG,
                      relief="flat", bd=0, cursor="hand2",
                      command=open_cal).grid(row=0, column=1, padx=(4, 0))
            race_entries[key] = var
            return var

        def _race_field(parent, row, key, label, default=""):
            tk.Label(parent, text=label, font=("Helvetica", 9, "bold"), bg=BG, fg=FG).grid(
                row=row, column=0, sticky="w", padx=(0, 8), pady=4)
            var = tk.StringVar(value=str(data.get(key, default) or default))
            e = tk.Entry(parent, textvariable=var, font=("Helvetica", 10), relief="solid", bd=1)
            e.grid(row=row, column=1, sticky="ew", pady=4)
            race_entries[key] = var
            return var

        _race_field(race_frame, 0, 'titolo',     "Titolo corsa")
        _race_date_field(race_frame, 1, 'data_inizio', "Data inizio",
                         data.get('data_inizio') or data.get('data') or date.today().isoformat())
        _race_date_field(race_frame, 2, 'data_fine',   "Data fine",
                         data.get('data_fine') or '')
        _race_field(race_frame, 3, 'luogo',       "Luogo")

        # Genere combo
        tk.Label(race_frame, text="Genere", font=("Helvetica", 9, "bold"), bg=BG, fg=FG).grid(
            row=4, column=0, sticky="w", padx=(0, 8), pady=4)
        genere_var = tk.StringVar(value=data.get('genere', 'Femminile'))
        tk.OptionMenu(race_frame, genere_var, *GENERI).grid(row=4, column=1, sticky="ew", pady=4)
        race_entries['genere'] = genere_var

        # Categoria checkboxes
        tk.Label(race_frame, text="Categorie", font=("Helvetica", 9, "bold"), bg=BG, fg=FG).grid(
            row=5, column=0, sticky="w", padx=(0, 8), pady=4)
        cat_frame = tk.Frame(race_frame, bg=BG)
        cat_frame.grid(row=5, column=1, sticky="ew", pady=4)
        current_cats = data.get('categoria', ['Junior'])
        if isinstance(current_cats, str):
            current_cats = [current_cats]
        cat_vars: dict[str, tk.BooleanVar] = {}
        for cat in CATEGORIE:
            v = tk.BooleanVar(value=cat in current_cats)
            tk.Checkbutton(cat_frame, text=cat, variable=v, bg=BG,
                           font=("Helvetica", 9)).pack(side="left", padx=(0, 10))
            cat_vars[cat] = v
        race_entries['categoria'] = cat_vars

        # World Tour (WT)
        tk.Label(race_frame, text="World Tour (WT)", font=("Helvetica", 9, "bold"), bg=BG, fg=FG).grid(
            row=6, column=0, sticky="w", padx=(0, 8), pady=4)
        wt_var = tk.BooleanVar(value=bool(data.get('wt', False)))
        tk.Checkbutton(race_frame, text="Corsa di categoria WT", variable=wt_var, bg=BG,
                       font=("Helvetica", 9)).grid(row=6, column=1, sticky="w", pady=4)
        race_entries['wt'] = wt_var

        # Serie
        _race_field(race_frame, 7, 'race_series', "Serie")

        # Slug (auto-generato)
        tk.Label(race_frame, text="Slug corsa", font=("Helvetica", 9, "bold"), bg=BG, fg=FG).grid(
            row=8, column=0, sticky="w", padx=(0, 8), pady=4)
        original_slug = data.get('slug', '')
        slug_var = tk.StringVar(value=original_slug)
        slug_entry = tk.Entry(race_frame, textvariable=slug_var, font=("Helvetica", 10), relief="solid", bd=1)
        slug_entry.grid(row=8, column=1, sticky="ew", pady=4)
        race_entries['slug'] = slug_var
        slug_manual = [not is_new]  # se edit, lo slug non viene auto-rigenerato

        def _auto_slug(*_):
            if slug_manual[0]:
                return
            titolo = race_entries['titolo'].get().strip()
            data_s = race_entries['data_inizio'].get().strip()
            year = data_s.split('-')[0] if len(data_s) >= 4 else "2026"
            genere = race_entries['genere'].get()
            cats = [c for c, v in cat_vars.items() if v.get()]
            cat_code_str = '-'.join(
                categoria_code(genere, c) for c in ['Allievi', 'Junior', 'U23', 'Elite'] if c in cats
            )
            if titolo:
                new_slug = slugify(titolo) + f"-{year}"
                if cat_code_str:
                    new_slug += f"-{cat_code_str}"
            else:
                new_slug = ""
            slug_var.set(new_slug)
            _refresh_stage_slugs()

        race_entries['titolo'].trace_add("write", _auto_slug)
        race_entries['data_inizio'].trace_add("write", _auto_slug)
        genere_var.trace_add("write", _auto_slug)
        for v in cat_vars.values():
            v.trace_add("write", _auto_slug)
        slug_entry.bind("<KeyPress>", lambda e: slug_manual.__setitem__(0, True))

        # ── Sezione 2: Tappe ───────────────────────────────────────────────
        stages_outer = tk.LabelFrame(scroll_frame, text="Tappe",
                                     bg=BG, fg=FG, font=("Helvetica", 10, "bold"),
                                     padx=10, pady=8)
        stages_outer.pack(fill="both", expand=True, padx=14, pady=(0, 8))

        # Lista a sinistra + dettaglio a destra
        stages_pane = tk.Frame(stages_outer, bg=BG)
        stages_pane.pack(fill="both", expand=True)

        left_pane = tk.Frame(stages_pane, bg=BG, width=220)
        left_pane.pack(side="left", fill="y", padx=(0, 8))
        left_pane.pack_propagate(False)

        lf = tk.Frame(left_pane, bg="white", relief="solid", bd=1)
        lf.pack(fill="both", expand=True)
        s_scroll = tk.Scrollbar(lf)
        s_scroll.pack(side="right", fill="y")
        stage_listbox = tk.Listbox(lf, yscrollcommand=s_scroll.set, bg="white",
                                   selectmode="single", font=("Courier", 9), bd=0, width=22, height=10)
        stage_listbox.pack(side="left", fill="both", expand=True)
        s_scroll.config(command=stage_listbox.yview)

        btns_l = tk.Frame(left_pane, bg=BG)
        btns_l.pack(fill="x", pady=(6, 0))
        tk.Button(btns_l, text="+ Aggiungi Tappa", font=("Helvetica", 8), bg="#059669",
                  fg="white", relief="flat", bd=0, cursor="hand2",
                  command=lambda: _add_stage()).pack(fill="x", pady=(0, 3))
        tk.Button(btns_l, text="− Rimuovi Tappa", font=("Helvetica", 8), bg="#dc2626",
                  fg="white", relief="flat", bd=0, cursor="hand2",
                  command=lambda: _remove_stage()).pack(fill="x")

        # Pannello dettaglio tappa (destra)
        right_pane = tk.Frame(stages_pane, bg=BG)
        right_pane.pack(side="left", fill="both", expand=True)

        detail_lf = tk.LabelFrame(right_pane, text="Dettaglio tappa selezionata",
                                   bg=BG, fg=FG, font=("Helvetica", 9, "bold"),
                                   padx=8, pady=6)
        detail_lf.pack(fill="both", expand=True)
        detail_lf.columnconfigure(1, weight=1)

        stage_entries: dict[str, tk.Variable] = {}
        stage_widgets: dict[str, tk.Widget] = {}

        def _make_detail_field(parent, row, key, label, default=""):
            tk.Label(parent, text=label, font=("Helvetica", 9, "bold"), bg=BG, fg=FG).grid(
                row=row, column=0, sticky="w", padx=(0, 6), pady=3)
            var = tk.StringVar(value=default)
            e = tk.Entry(parent, textvariable=var, font=("Helvetica", 9), relief="solid", bd=1)
            e.grid(row=row, column=1, sticky="ew", pady=3)
            stage_entries[key] = var
            stage_widgets[key] = e
            return var

        def _make_detail_date_field(parent, row, key, label):
            """Come _make_detail_field ma con bottone 📅 per aprire il calendario.
            Per le tappe, limita il range al data_inizio - data_fine della corsa."""
            tk.Label(parent, text=label, font=("Helvetica", 9, "bold"), bg=BG, fg=FG).grid(
                row=row, column=0, sticky="w", padx=(0, 6), pady=3)
            f = tk.Frame(parent, bg=BG)
            f.grid(row=row, column=1, sticky="ew", pady=3)
            f.columnconfigure(0, weight=1)
            var = tk.StringVar()
            tk.Entry(f, textvariable=var, font=("Helvetica", 9), relief="solid", bd=1).grid(
                row=0, column=0, sticky="ew")
            # Bottone calendario: passa il range della corsa a tappe
            tk.Button(f, text="📅", font=("Helvetica", 10), bg=BG, fg=FG,
                      relief="flat", bd=0, cursor="hand2",
                      command=lambda sv=var: _open_calendar(
                          win, sv,
                          min_date=race_entries['data_inizio'].get(),
                          max_date=race_entries['data_fine'].get()
                      )).grid(
                row=0, column=1, padx=(4, 0))
            stage_entries[key] = var
            return var

        # Numero tappa (editabile per riordinare)
        tk.Label(detail_lf, text="Numero tappa", font=("Helvetica", 9, "bold"), bg=BG, fg=FG).grid(
            row=0, column=0, sticky="w", padx=(0, 6), pady=3)
        numero_tappa_var = tk.IntVar(value=1)
        tk.Spinbox(detail_lf, from_=1, to=99, textvariable=numero_tappa_var,
                   font=("Helvetica", 9), width=6).grid(row=0, column=1, sticky="w", pady=3)
        stage_entries['numero'] = numero_tappa_var
        
        _make_detail_field(detail_lf, 1, 'nome',         "Nome Tappa")
        _make_detail_date_field(detail_lf, 2, 'data',    "Data")
        _make_detail_field(detail_lf, 3, 'distanza_km',  "Distanza (km)")
        _make_detail_field(detail_lf, 4, 'dislivello_m', "Dislivello (m)")
        _make_detail_field(detail_lf, 5, 'velocita_media_kmh', "Velocità media (km/h)")

        # Giri
        tk.Label(detail_lf, text="Giri circuito", font=("Helvetica", 9, "bold"), bg=BG, fg=FG).grid(
            row=6, column=0, sticky="w", padx=(0, 6), pady=3)
        giri_var = tk.IntVar(value=1)
        tk.Spinbox(detail_lf, from_=1, to=50, textvariable=giri_var,
                   font=("Helvetica", 9), width=6).grid(row=6, column=1, sticky="w", pady=3)
        stage_entries['giri'] = giri_var

        def _on_giri_change(*_):
            idx = selected_stage[0]
            if idx is None:
                return
            try:
                giri = max(1, int(giri_var.get()))
            except (ValueError, TypeError):
                return
            base_km   = stages[idx].get('_base_km')
            base_elev = stages[idx].get('_base_elev')
            if base_km is not None:
                stage_entries['distanza_km'].set(str(round(base_km * giri, 2)))
            if base_elev is not None:
                stage_entries['dislivello_m'].set(str(round(base_elev * giri)))

        giri_var.trace_add("write", _on_giri_change)

        tk.Label(detail_lf, text="Disciplina", font=("Helvetica", 9, "bold"), bg=BG, fg=FG).grid(
            row=7, column=0, sticky="w", padx=(0, 6), pady=3)
        disc_s_var = tk.StringVar(value="Strada")
        disc_s_menu = tk.OptionMenu(detail_lf, disc_s_var, *DISCIPLINE)
        disc_s_menu.config(font=("Helvetica", 9))
        disc_s_menu.grid(row=7, column=1, sticky="ew", pady=3)
        stage_entries['disciplina'] = disc_s_var
        
        # ── Gestione Tipo pista per le tappe: azzera km e dislivello ────────────
        km_dislivello_backup_s = {'distanza_km': None, 'dislivello_m': None}
        
        def _on_stage_disciplina_change(*args):
            """Quando disciplina della tappa cambia: se è Tipo pista, svuota km e dislivello"""
            disciplina_val = disc_s_var.get()
            
            if disciplina_val == "Tipo pista":
                # Salva i valori attuali prima di cancellare
                km_dislivello_backup_s['distanza_km'] = stage_entries['distanza_km'].get() or None
                km_dislivello_backup_s['dislivello_m'] = stage_entries['dislivello_m'].get() or None
                
                # Svuota i campi
                stage_entries['distanza_km'].delete(0, tk.END)
                stage_entries['dislivello_m'].delete(0, tk.END)
            else:
                # Se torna a un'altra disciplina e c'è un backup, ripristina
                if km_dislivello_backup_s['distanza_km'] and km_dislivello_backup_s['distanza_km'] != 'None':
                    stage_entries['distanza_km'].delete(0, tk.END)
                    stage_entries['distanza_km'].insert(0, str(km_dislivello_backup_s['distanza_km']))
                if km_dislivello_backup_s['dislivello_m'] and km_dislivello_backup_s['dislivello_m'] != 'None':
                    stage_entries['dislivello_m'].delete(0, tk.END)
                    stage_entries['dislivello_m'].insert(0, str(km_dislivello_backup_s['dislivello_m']))
        
        disc_s_var.trace_add("write", _on_stage_disciplina_change)

        _make_detail_field(detail_lf, 8, 'luogo', "Luogo")

        # Riga slug tappa con bottone rigenerazione
        tk.Label(detail_lf, text="Slug tappa", font=("Helvetica", 9, "bold"), bg=BG, fg=FG).grid(
            row=9, column=0, sticky="w", padx=(0, 6), pady=3)
        slug_frame = tk.Frame(detail_lf, bg=BG)
        slug_frame.grid(row=9, column=1, sticky="ew", pady=3)
        slug_frame.columnconfigure(0, weight=1)
        
        slug_t_var = tk.StringVar()
        slug_t_entry = tk.Entry(slug_frame, textvariable=slug_t_var, font=("Helvetica", 9),
                                state="readonly", relief="solid", bd=1,
                                readonlybackground="#ede9e2")
        slug_t_entry.grid(row=0, column=0, sticky="ew")
        
        def _regenerate_stage_slug():
            """Rigenerazione dello slug della tappa basato su numero e dati principali"""
            try:
                num = int(numero_tappa_var.get())
            except (ValueError, TypeError):
                num = selected_stage[0] + 1 if selected_stage[0] is not None else 1
            novo_slug = _stage_auto_slug(num)
            slug_t_var.set(novo_slug)
            # Aggiorna anche nel dict stages
            idx = selected_stage[0]
            if idx is not None:
                stages[idx]['slug_tappa'] = novo_slug
        
        tk.Button(slug_frame, text="🔄", font=("Helvetica", 10), bg=BG, fg=FG,
                  relief="flat", bd=0, cursor="hand2",
                  command=_regenerate_stage_slug).grid(row=0, column=1, padx=(4, 0))
        
        stage_entries['slug_tappa'] = slug_t_var

        # Stato GPX
        tk.Label(detail_lf, text="GPX", font=("Helvetica", 9, "bold"), bg=BG, fg=FG).grid(
            row=10, column=0, sticky="w", padx=(0, 6), pady=3)
        gpx_status_var = tk.StringVar(value="Nessun GPX caricato")
        gpx_status_lbl = tk.Label(detail_lf, textvariable=gpx_status_var,
                                   font=("Helvetica", 9), bg=BG, fg="#7a746b")
        gpx_status_lbl.grid(row=10, column=1, sticky="w", pady=3)

        gpx_btn_frame = tk.Frame(detail_lf, bg=BG)
        gpx_btn_frame.grid(row=11, column=0, columnspan=2, sticky="ew", pady=(4, 0))

        def _load_gpx_for_stage():
            idx = selected_stage[0]
            if idx is None:
                messagebox.showwarning("Attenzione", "Seleziona una tappa prima", parent=win)
                return
            gpx_path = filedialog.askopenfilename(
                title="Seleziona GPX per la tappa",
                filetypes=[("GPX files", "*.gpx"), ("All files", "*.*")],
                parent=win
            )
            if not gpx_path:
                return
            gpx_data = parse_gpx(Path(gpx_path))
            if not gpx_data.get('gpx_points'):
                messagebox.showwarning("Attenzione", "Il file GPX non contiene dati validi", parent=win)
                return
            stages[idx]['gpx_points'] = gpx_data['gpx_points']
            stages[idx]['_base_km']   = gpx_data.get('distanza_km')
            stages[idx]['_base_elev'] = gpx_data.get('dislivello_m')
            try:
                giri = int(stage_entries['giri'].get())
            except (ValueError, TypeError):
                giri = 1
            giri = max(1, giri)
            if gpx_data.get('distanza_km'):
                km_val = round(gpx_data['distanza_km'] * giri, 2)
                stage_entries['distanza_km'].set(str(km_val))
                stages[idx]['distanza_km'] = km_val
            if gpx_data.get('dislivello_m'):
                elev_val = round(gpx_data['dislivello_m'] * giri)
                stage_entries['dislivello_m'].set(str(elev_val))
                stages[idx]['dislivello_m'] = elev_val
            
            # Auto-rileva luogo dalle coordinate del GPX
            if gpx_data.get('center_lat') and gpx_data.get('center_lon'):
                luogo = reverse_geocode(gpx_data['center_lat'], gpx_data['center_lon'])
                if luogo:
                    stage_entries['luogo'].set(luogo)
                    stages[idx]['luogo'] = luogo
            
            gpx_status_var.set("✓ GPX caricato")
            gpx_status_lbl.config(fg="#059669")
            messagebox.showinfo("Successo", "GPX caricato per la tappa!", parent=win)

        def _clear_gpx_for_stage():
            idx = selected_stage[0]
            if idx is None:
                return
            stages[idx]['gpx_points'] = None
            stages[idx].pop('_base_km',   None)
            stages[idx].pop('_base_elev', None)
            gpx_status_var.set("Nessun GPX caricato")
            gpx_status_lbl.config(fg="#7a746b")

        tk.Button(gpx_btn_frame, text="📁 Carica GPX", font=("Helvetica", 8),
                  bg="#8b5cf6", fg="white", relief="flat", bd=0, cursor="hand2",
                  command=_load_gpx_for_stage).pack(side="left", padx=(0, 6))
        tk.Button(gpx_btn_frame, text="✕ Rimuovi GPX", font=("Helvetica", 8),
                  bg="#6b7280", fg="white", relief="flat", bd=0, cursor="hand2",
                  command=_clear_gpx_for_stage).pack(side="left")

        # Bottone salva tappa (applica al dict stages)
        def _save_current_stage():
            idx = selected_stage[0]
            if idx is None:
                return
            try:
                km = float(stage_entries['distanza_km'].get()) if stage_entries['distanza_km'].get().strip() else None
            except ValueError:
                km = None
            try:
                elev = float(stage_entries['dislivello_m'].get()) if stage_entries['dislivello_m'].get().strip() else None
            except ValueError:
                elev = None
            try:
                vel = float(stage_entries['velocita_media_kmh'].get()) if stage_entries['velocita_media_kmh'].get().strip() else None
            except ValueError:
                vel = None
            try:
                giri = int(stage_entries['giri'].get())
            except (ValueError, TypeError):
                giri = 1
            try:
                nuovo_numero = int(numero_tappa_var.get())
            except (ValueError, TypeError):
                nuovo_numero = stages[idx].get('numero', idx + 1)
            
            # Se il numero è cambiato, è necessario riordinare le tappe
            old_numero = stages[idx]['numero']
            if nuovo_numero != old_numero:
                # Sposta la tappa nella lista
                stage = stages.pop(idx)
                stage['numero'] = nuovo_numero
                # Inserisci nella posizione corretta (numero - 1)
                insertion_pos = min(nuovo_numero - 1, len(stages))
                stages.insert(insertion_pos, stage)
                # Rinumera tutte le tappe per assicurare coerenza
                for i, s in enumerate(stages):
                    s['numero'] = i + 1
                selected_stage[0] = stages.index(stage)
            else:
                stages[idx]['numero'] = nuovo_numero
            
            stages[idx]['nome']         = stage_entries['nome'].get().strip()
            stages[idx]['data']         = stage_entries['data'].get().strip()
            stages[idx]['distanza_km']  = km
            stages[idx]['dislivello_m'] = elev
            stages[idx]['velocita_media_kmh'] = vel
            stages[idx]['disciplina']   = stage_entries['disciplina'].get()
            stages[idx]['luogo']        = stage_entries['luogo'].get().strip()
            stages[idx]['giri']         = max(1, giri)
            stages[idx]['slug_tappa']   = slug_t_var.get()
            
            # Se la tappa è Tipo pista, forza distanza_km e dislivello_m a None (non conteggiati)
            if stages[idx]['disciplina'] == 'Tipo pista':
                stages[idx]['distanza_km'] = None
                stages[idx]['dislivello_m'] = None
            
            _refresh_stages_list()

        tk.Button(detail_lf, text="Applica modifiche tappa", font=("Helvetica", 9, "bold"),
                  bg=ACCENT, fg="white", relief="flat", bd=0, cursor="hand2",
                  command=_save_current_stage).grid(row=12, column=0, columnspan=2,
                                                    sticky="ew", pady=(8, 0))

        # ── Helper: auto slug tappa ─────────────────────────────────────────
        def _stage_auto_slug(stage_num: int) -> str:
            base_slug = slug_var.get().strip()
            # Rimuovi il codice cat alla fine per reinserirlo dopo S{N}
            # Il slug di una tappa è: {base_slug_senza_cat}-S{N}-{year}-{cat_code}
            # Però il race slug è già nella forma nome-year-CAT, quindi usiamo:
            # prendiamo il nome-year-CAT e inseriamo S{N} prima del year
            # Es: "cittiglio-tour-2026-DJ" → "cittiglio-tour-S2-2026-DJ"
            import re as _re
            # Prova a inserire S{N} prima dell'anno (4 cifre)
            m = _re.search(r'-(\d{4})-', base_slug)
            if m:
                pos = m.start()
                return base_slug[:pos] + f"-S{stage_num}" + base_slug[pos:]
            else:
                return base_slug + f"-S{stage_num}" if base_slug else f"tappa-S{stage_num}"

        def _refresh_stage_slugs():
            for i, s in enumerate(stages):
                s['slug_tappa'] = _stage_auto_slug(s.get('numero', i + 1))
            _refresh_stages_list()

        # ── Helper: aggiorna listbox tappe ──────────────────────────────────
        def _refresh_stages_list():
            stage_listbox.delete(0, tk.END)
            for s in stages:
                gpx_mark = "✓" if s.get('gpx_points') else "—"
                stage_listbox.insert(tk.END, f"S{s['numero']:>2}: {s.get('nome','?')[:16]:<16} {gpx_mark}")
            # Ri-seleziona
            if selected_stage[0] is not None and selected_stage[0] < len(stages):
                stage_listbox.selection_set(selected_stage[0])

        # ── Helper: carica dettagli tappa nel pannello ──────────────────────
        def _load_stage_detail(idx: int):
            if idx is None or idx >= len(stages):
                return
            s = stages[idx]
            numero_tappa_var.set(int(s.get('numero', idx + 1)))
            stage_entries['nome'].set(s.get('nome', ''))
            stage_entries['data'].set(s.get('data', ''))
            stage_entries['distanza_km'].set(str(s.get('distanza_km', '') or ''))
            stage_entries['dislivello_m'].set(str(s.get('dislivello_m', '') or ''))
            stage_entries['velocita_media_kmh'].set(str(s.get('velocita_media_kmh', '') or ''))
            stage_entries['disciplina'].set(s.get('disciplina', 'Strada'))
            stage_entries['luogo'].set(s.get('luogo', ''))
            stage_entries['giri'].set(int(s.get('giri', 1)))
            slug_t_var.set(s.get('slug_tappa', _stage_auto_slug(s.get('numero', idx + 1))))
            if s.get('gpx_points'):
                gpx_status_var.set("✓ GPX caricato")
                gpx_status_lbl.config(fg="#059669")
            else:
                gpx_status_var.set("Nessun GPX caricato")
                gpx_status_lbl.config(fg="#7a746b")

        def _on_stage_select(event):
            sel = stage_listbox.curselection()
            if not sel:
                return
            new_idx = sel[0]
            if selected_stage[0] == new_idx:
                return
            _save_current_stage()  # salva la tappa precedente prima di cambiare
            selected_stage[0] = new_idx
            _load_stage_detail(new_idx)
            # Ripristina la selezione corretta nel listbox (corretta dopo _refresh_stages_list)
            stage_listbox.selection_clear(0, tk.END)
            stage_listbox.selection_set(new_idx)

        stage_listbox.bind("<<ListboxSelect>>", _on_stage_select)

        # ── Aggiungi / Rimuovi tappa ─────────────────────────────────────────
        def _add_stage():
            _save_current_stage()  # salva quella attuale prima
            num = len(stages) + 1
            new_s = {
                'numero':       num,
                'nome':         f"Tappa {num}",
                'slug_tappa':   _stage_auto_slug(num),
                'data':         race_entries['data_inizio'].get(),
                'disciplina':   'Strada',
                'giri':         1,
                'distanza_km':  None,
                'dislivello_m': None,
                'luogo':        None,
                'velocita_media_kmh': None,
                'gpx_points':   None,
            }
            stages.append(new_s)
            _refresh_stages_list()
            # Seleziona la nuova tappa
            stage_listbox.selection_clear(0, tk.END)
            stage_listbox.selection_set(len(stages) - 1)
            selected_stage[0] = len(stages) - 1
            _load_stage_detail(selected_stage[0])

        def _remove_stage():
            idx = selected_stage[0]
            if idx is None:
                messagebox.showwarning("Attenzione", "Seleziona una tappa da rimuovere", parent=win)
                return
            ok = messagebox.askyesno("Conferma", f"Rimuovere '{stages[idx].get('nome', '')}'?", parent=win)
            if not ok:
                return
            # Traccia lo slug della tappa rimossa come orfano
            removed_slug = stages[idx].get('slug_tappa', '')
            if removed_slug:
                orphaned_stage_slugs.add(removed_slug)
            stages.pop(idx)
            # Rinumera: traccia i vecchi slug prima di sovrascriverli
            for i, s in enumerate(stages):
                old_slug = s.get('slug_tappa', '')
                s['numero'] = i + 1
                s['slug_tappa'] = _stage_auto_slug(i + 1)
                if old_slug and old_slug != s['slug_tappa']:
                    orphaned_stage_slugs.add(old_slug)
            selected_stage[0] = None
            _refresh_stages_list()
            # svuota dettaglio
            for k in ['nome', 'data', 'distanza_km', 'dislivello_m']:
                stage_entries[k].set('')
            gpx_status_var.set("Nessun GPX caricato")

        # Popola inizialmente
        _refresh_stages_list()
        if stages:
            stage_listbox.selection_set(0)
            selected_stage[0] = 0
            _load_stage_detail(0)

        if is_new:
            _auto_slug()

        # ── Bottoni finali ───────────────────────────────────────────────────
        btn_frame = tk.Frame(scroll_frame, bg=BG, padx=14, pady=10)
        btn_frame.pack(fill="x")

        def _save_all():
            _save_current_stage()  # assicura che l'ultima tappa sia salvata

            titolo      = race_entries['titolo'].get().strip()
            data_inizio = race_entries['data_inizio'].get().strip()
            data_fine   = race_entries['data_fine'].get().strip()
            luogo       = race_entries['luogo'].get().strip()
            genere      = race_entries['genere'].get()
            race_series = race_entries['race_series'].get().strip()
            cats        = [c for c in CATEGORIE if cat_vars[c].get()]
            race_slug   = race_entries['slug'].get().strip()

            if not titolo:
                messagebox.showerror("Errore", "Titolo obbligatorio", parent=win); return
            if not race_slug:
                messagebox.showerror("Errore", "Slug obbligatorio", parent=win); return
            if not data_inizio:
                messagebox.showerror("Errore", "Data inizio obbligatoria", parent=win); return
            if data_fine and data_fine < data_inizio:
                messagebox.showerror("Errore", "La data di fine non può essere precedente alla data di inizio", parent=win); return
            if not cats:
                messagebox.showerror("Errore", "Seleziona almeno una categoria", parent=win); return
            if not stages:
                messagebox.showerror("Errore", "Aggiungi almeno una tappa", parent=win); return
            for s in stages:
                if not s.get('nome'):
                    messagebox.showerror("Errore", f"Tappa {s['numero']}: nome obbligatorio", parent=win)
                    return

            main = {
                'titolo':       titolo,
                'race_series':  race_series or slugify(titolo),
                'data':         data_inizio,   # backward compat per index/filtri
                'data_inizio':  data_inizio,
                'data_fine':    data_fine or None,
                'genere':       genere,
                'categoria':    cats,
                'luogo':        luogo or None,
            }
            
            # Aggiungi WT se selezionato
            if race_entries['wt'].get():
                main['wt'] = True

            save_stage_race(race_slug, main, stages)

            # In edit mode, se lo slug della corsa è cambiato, elimina i vecchi file principali
            if not is_new and original_slug and original_slug != race_slug:
                for p in [
                    GARE_DIR / f"{original_slug}.json",
                    PUBLIC_GARE_DIR / f"{original_slug}.json",
                ]:
                    if p.exists():
                        p.unlink()
                # Segna tutte le tappe con il vecchio slug come orfane
                if data.get('tappe'):
                    for old_tappa in data['tappe']:
                        old_stage_slug = old_tappa.get('slug', '')
                        if old_stage_slug:
                            orphaned_stage_slugs.add(old_stage_slug)

            # Elimina file orfani (tappe rimosse o rinumerate con slug diverso)
            current_stage_slugs = {s['slug_tappa'] for s in stages}
            for orphan_slug in orphaned_stage_slugs - current_stage_slugs:
                for p in [
                    GARE_DIR / f"{orphan_slug}.json",
                    PUBLIC_GARE_DIR / f"{orphan_slug}.json",
                    GPX_DIR / f"{orphan_slug}-gpx.json",
                    PUBLIC_GPX_DIR / f"{orphan_slug}-gpx.json",
                ]:
                    if p.exists():
                        p.unlink()

            messagebox.showinfo("Salvato", "Corsa a tappe salvata con successo!", parent=win)
            win.destroy()
            self.refresh_list()

        tk.Button(btn_frame, text="💾 Salva corsa a tappe", font=("Helvetica", 10, "bold"),
                  bg="#059669", fg="white", padx=14, pady=8, relief="flat", bd=0,
                  cursor="hand2", command=_save_all).pack(side="left", padx=(0, 8))
        tk.Button(btn_frame, text="Annulla", font=("Helvetica", 10),
                  bg="#d1d5db", fg=FG, padx=14, pady=8, relief="flat", bd=0,
                  cursor="hand2", command=win.destroy).pack(side="left")

        # Dimensione finestra
        win.update_idletasks()
        win.minsize(720, 800)
        win.geometry("750x900")

    def edit_race(self):
        """Modifica metadati della gara selezionata"""
        idx = self.race_listbox.curselection()
        if not idx:
            messagebox.showwarning("Attenzione", "Seleziona una gara prima")
            return
        
        # Usa il mapping per trovare lo slug dalla posizione nel listbox
        slug = self.listbox_index_map.get(idx[0])
        if not slug:
            messagebox.showwarning("Attenzione", "Gara non trovata")
            return
        
        # Carica i dati
        data = None
        for s, d in self.filtered_races:
            if s == slug:
                data = d
                break
        
        # Se non trovato nella cache, potrebbe essere una tappa -> carica dal JSON
        if not data:
            tappa_json_path = GARE_DIR / f"{slug}.json"
            if tappa_json_path.exists():
                try:
                    data = json.loads(tappa_json_path.read_text(encoding='utf-8'))
                except Exception:
                    messagebox.showerror("Errore", "Impossibile caricare i dati della tappa")
                    return
            else:
                messagebox.showwarning("Attenzione", "Gara non trovata")
                return
        
        # Se è una tappa, carica la corsa a tappe principale
        if data.get('tipo') == 'tappa':
            stage_race_slug = data.get('corsa_a_tappe_slug')
            if stage_race_slug:
                stage_race_path = GARE_DIR / f"{stage_race_slug}.json"
                if stage_race_path.exists():
                    try:
                        stage_race_data = json.loads(stage_race_path.read_text(encoding='utf-8'))
                        self.open_stage_race_form(initial_data=stage_race_data.copy(), is_new=False)
                        return
                    except Exception as e:
                        messagebox.showerror("Errore", f"Impossibile caricare la corsa a tappe: {e}")
                        return
            messagebox.showwarning("Attenzione", "Corsa a tappe principale non trovata")
            return
        elif data.get('tipo') == 'corsa_a_tappe':
            self.open_stage_race_form(initial_data=data.copy(), is_new=False)
        else:
            self.open_add_race_form(data.copy(), is_new=False, original_slug=slug)
    
    
    def delete_race(self):
        """Elimina race"""
        idx = self.race_listbox.curselection()
        if not idx:
            messagebox.showwarning("Attenzione", "Seleziona una gara prima")
            return
        
        # Usa il mapping per trovare lo slug dalla posizione nel listbox
        slug = self.listbox_index_map.get(idx[0])
        if not slug:
            messagebox.showwarning("Attenzione", "Gara non trovata")
            return
        
        # Carica i dati
        data = None
        for s, d in self.filtered_races:
            if s == slug:
                data = d
                break
        
        # Se non trovato, carica dal JSON se è una tappa
        if not data:
            tappa_json_path = GARE_DIR / f"{slug}.json"
            if tappa_json_path.exists():
                try:
                    data = json.loads(tappa_json_path.read_text(encoding='utf-8'))
                except Exception:
                    messagebox.showerror("Errore", "Impossibile caricare i dati della tappa")
                    return
        
        if not data:
            messagebox.showwarning("Attenzione", "Gara non trovata")
            return
        
        title = data.get("titolo", slug)
        tipo  = data.get('tipo', '')
        
        if tipo == 'corsa_a_tappe':
            n = data.get('n_tappe', 0)
            ok = messagebox.askyesno(
                "Conferma",
                f"Eliminare '{title}' e TUTTE le sue {n} tappe?\nQuesta azione è irreversibile."
            )
            if ok:
                delete_stage_race(slug, data.get('tappe', []))
                messagebox.showinfo("Eliminato", "Corsa a tappe e tutte le tappe rimosse dal database")
                self.refresh_list()
        else:
            ok = messagebox.askyesno("Conferma", f"Eliminare '{title}'?\nQuesta azione è irreversibile.")
            if ok:
                delete_race(slug)
                messagebox.showinfo("Eliminato", "Gara rimossa dal database")
                self.refresh_list()
    
    def push_changes(self):
        """Esegue git push automatico"""
        success, msg = git_push_changes()
        if success:
            messagebox.showinfo("Git Push", msg)
        else:
            messagebox.showerror("Errore Git", msg)


if __name__ == "__main__":
    root = tk.Tk()
    app = RaceManagerApp(root)
    root.mainloop()
