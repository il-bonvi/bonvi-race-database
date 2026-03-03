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
GARE_DIR = ARCHIVIO_DIR / "gare-sorgenti"
GARE_DIR.mkdir(parents=True, exist_ok=True)


# ── UTILITY FUNCTIONS ─────────────────────────────────────────────────────────

def slugify(s: str) -> str:
    """Converte una stringa in slug URL-safe"""
    import unicodedata
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = s.lower()
    s = re.sub(r'[^a-z0-9]+', '-', s)
    return s.strip('-')


def reverse_geocode(lat: float, lon: float) -> str | None:
    """Ritorna 'Provincia, Regione, IT' tramite Nominatim (OpenStreetMap)."""
    import urllib.request
    import urllib.parse
    import json as _json
    
    try:
        params = urllib.parse.urlencode({
            "lat": round(lat, 5),
            "lon": round(lon, 5),
            "format": "json",
            "zoom": 8,
        })
        url = f"https://nominatim.openstreetmap.org/reverse?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "RaceDB/1.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = _json.loads(response.read())
        
        address = data.get("address", {})
        provincia = address.get("county", address.get("province", ""))
        regione = address.get("state", address.get("region", ""))
        
        if provincia and regione:
            return f"{provincia}, {regione}, IT"
        elif regione:
            return f"{regione}, IT"
        return None
        
    except Exception:
        return None


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

        # Punto centrale per il geocoding
        mid = coords[len(coords) // 2]
        center_lat, center_lon = mid[0], mid[1]

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
            
            races.append({
                "slug": slug,
                "titolo": gara.get("titolo"),
                "data": data_str,
                "year": year,
                "race_series": gara.get("race_series"),
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

CATEGORIE = ["Elite", "U23", "Junior", "Allievi"]
GENERI = ["Maschile", "Femminile"]
DISCIPLINE = ["Strada", "Criterium", "Cronometro"]

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
    """Salva race JSON nella root (source of truth) e sincronizza in public/.
    """
    # Imposta race_series automaticamente dal titolo
    if 'titolo' in data:
        data['race_series'] = data['titolo']
    
    json_path = GARE_DIR / f"{slug}.json"
    data_clean = {k: v for k, v in data.items() if v is not None}
    json_str = json.dumps(data_clean, ensure_ascii=False, indent=2)
    
    json_path.write_text(json_str, encoding='utf-8')
    
    # Sincronizza anche in public/gare-sorgenti/ per il browser
    public_json_dir = ARCHIVIO_DIR / "public" / "gare-sorgenti"
    public_json_dir.mkdir(parents=True, exist_ok=True)
    public_json_path = public_json_dir / f"{slug}.json"
    public_json_path.write_text(json_str, encoding='utf-8')
    
    # Aggiorna l'indice per la navigazione tra serie
    update_gares_index()


def delete_race(slug: str):
    """Elimina race dalla root (source of truth) e sincronizza in public/.
    """
    json_path = GARE_DIR / f"{slug}.json"
    if json_path.exists():
        json_path.unlink()
    
    # Sincronizza eliminazione anche in public/gare-sorgenti/
    public_json_dir = ARCHIVIO_DIR / "public" / "gare-sorgenti"
    public_json_path = public_json_dir / f"{slug}.json"
    if public_json_path.exists():
        public_json_path.unlink()
    
    # Aggiorna l'indice per la navigazione tra serie
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
        
        if result.returncode != 0:
            if "fatal: could not read" in result.stderr:
                return False, "❌ Errore autenticazione Git:\nConfigura le credenziali con:\n  git config --global credential.helper store"
            else:
                return False, f"Errore git: {result.stderr}"
        
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
        self.root.geometry("1100x700")
        self.root.configure(bg=BG)
        
        self.root.option_add("*Background", BG)
        self.root.option_add("*Foreground", FG)
        self.root.option_add("*Font", ("Helvetica", 10))
        
        self.all_races = []  # Cache di tutte le gare
        self.filtered_races = []  # Gare filtrate
        
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
        
        tk.Button(button_frame, text="➕ Aggiungi nuova", font=("Helvetica", 10),
                 bg=ACCENT, fg="white", padx=12, pady=8, relief="flat", bd=0,
                 cursor="hand2", command=self.add_race).pack(side="left", padx=(0, 6))
        
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
        for slug, data in self.filtered_races:
            titolo = data.get('titolo', f'[{slug}]')
            data_gara = data.get('data', '—')
            km = data.get('distanza_km', '—')
            dislivello = data.get('dislivello_m', '—')
            line = f"{titolo:30s} | {data_gara} | {km:6}km | {dislivello:6}m"
            self.race_listbox.insert(tk.END, line)
    
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
        
        slug, data = self.filtered_races[idx[0]]
        
        gpx_count = len(data.get('gpx_points', []))
        info = f"""TITOLO:       {data.get('titolo', '—')}
SLUG:         {slug}
DATA:         {data.get('data', '—')}
GENERE:       {data.get('genere', '—')}
CATEGORIE:    {', '.join(data.get('categoria', [])) if isinstance(data.get('categoria'), list) else data.get('categoria', '—')}
DISCIPLINA:   {data.get('disciplina', '—')}
DISTANZA:     {data.get('distanza_km', '—')} km
DISLIVELLO:   {data.get('dislivello_m', '—')} m
LUOGO:        {data.get('luogo', '—')}
NOTE:         {(data.get('note', '') or '')[:100]}
GPX POINTS:   {gpx_count} punti"""
        
        self.info_text.config(state="normal")
        self.info_text.delete(1.0, tk.END)
        self.info_text.insert(1.0, info)
        self.info_text.config(state="disabled")
    
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
            'data': date.today().isoformat(),
            'genere': 'Femminile',
            'categoria': ['Junior'],
            'disciplina': 'Strada',
            'giri': 1,
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
        """Aggiunge gara referenziando GPX di una gara esistente"""
        # Dialog per scegliere quale gara
        existing_races = [(s, d.get('titolo', s), d.get('data', '')) 
                         for s, d in self.all_races 
                         if d.get('gpx_points')]
        existing_races.sort(key=lambda x: x[2], reverse=True)
        
        if not existing_races:
            messagebox.showwarning("Attenzione", "Non ci sono gare con GPX nel database")
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
            slug_ref, titolo_ref, data_ref = existing_races[actual_idx]
            _, ref_data = next((s, d) for s, d in self.all_races if s == slug_ref)
            
            # Crea nuova gara con riferimento
            new_data = {
                'titolo': titolo_ref,
                'data': date.today().isoformat(),
                'genere': 'Femminile',
                'categoria': ['Junior'],
                'disciplina': 'Strada',
                'giri': 1,
                'gpx_reference': slug_ref,
                'distanza_km': ref_data.get('distanza_km'),
                'dislivello_m': ref_data.get('dislivello_m'),
            }
            
            # Aggiungi il luogo della gara di riferimento se esiste
            if ref_data.get('luogo'):
                new_data['luogo'] = ref_data.get('luogo')
            
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
        
        # Ottieni lista di tutte le gare per il riferimento GPX
        tutte_le_gare = [(s, d.get('titolo', s)) for s, d in self.all_races 
                        if d.get('gpx_points') and (not is_new or True)]
        tutte_le_gare.sort(key=lambda x: x[1])
        opzioni_gare = ["[Nessun riferimento]"] + [f"{titolo} ({s})" for s, titolo in tutte_le_gare]
        opzioni_gare_vals = [""] + [s for s, titolo in tutte_le_gare]
        
        fields = [
            ("slug", "Slug", "entry"),
            ("titolo", "Titolo", "entry"),
            ("data", "Data (AAAA-MM-GG)", "entry"),
            ("luogo", "Luogo", "entry"),
            ("giri", "Giri del circuito", "spinner"),
            ("distanza_km", "Distanza (km)", "entry"),
            ("dislivello_m", "Dislivello (m)", "entry"),
            ("velocita_media_kmh", "Velocità media prevista (km/h)", "entry"),
            ("genere", "Genere", "combo", GENERI),
            ("categoria", "Categorie", "categoria_checkboxes", CATEGORIE),
            ("disciplina", "Disciplina", "combo", DISCIPLINE),
            ("gpx_reference", "Usa GPX da gara precedente", "combo_gare", opzioni_gare, opzioni_gare_vals),
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
            else:
                entry = tk.Entry(edit_win, width=35, font=("Helvetica", 10))
                entry.insert(0, str(data.get(key, "") or ""))
                entry.grid(row=i, column=1, sticky="ew", padx=12, pady=6)
                entries[key] = entry
        
        # Auto-slug: quando cambia titolo o data, aggiorna slug automaticamente
        slug_manual = tk.BooleanVar(value=False)
        
        def update_slug(*args):
            """Aggiorna slug automaticamente dal titolo e data se non modificato manualmente"""
            if not slug_manual.get():
                try:
                    titolo = entries['titolo'].get().strip()
                    data_str = entries['data'].get().strip()
                    year = data_str.split('-')[0] if data_str and len(data_str) >= 4 else "2026"
                    new_auto_slug = slugify(titolo) + f"-{year}" if titolo else ""
                    
                    entries['slug'].delete(0, tk.END)
                    entries['slug'].insert(0, new_auto_slug)
                except:
                    pass
        
        # Collega i binding per titolo e data
        if isinstance(entries['titolo'], tk.Entry):
            entries['titolo'].bind("<KeyRelease>", update_slug)
        
        if isinstance(entries['data'], tk.Entry):
            entries['data'].bind("<KeyRelease>", update_slug)
            entries['data'].bind("<FocusOut>", update_slug)
        
        # Quando l'utente modifica lo slug manualmente, disabilita l'auto-update
        if isinstance(entries['slug'], tk.Entry):
            def on_slug_edit(event):
                slug_manual.set(True)
            entries['slug'].bind("<KeyPress>", on_slug_edit)
        
        # Genera slug iniziale
        update_slug()
        
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
                
                # Salva i punti GPX nei dati
                data['gpx_points'] = gpx_data['gpx_points']
                
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
                
                if key == "gpx_reference":
                    current_val = widget.get()
                    if not current_val or current_val == "[Nessun riferimento]":
                        if key in data:
                            del data[key]
                    else:
                        if "(" in current_val and current_val.endswith(")"):
                            slug_ref = current_val.split("(")[-1].rstrip(")")
                            data[key] = slug_ref
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
                data[key] = val
            
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
        
        tk.Button(button_frame, text="📁 Carica GPX", bg="#8b5cf6", fg="white", padx=12, pady=6,
                 relief="flat", bd=0, cursor="hand2", command=load_gpx_file).pack(side="left", padx=(0, 6))
        tk.Button(button_frame, text="Salva", bg=ACCENT, fg="white", padx=16, pady=6,
                 relief="flat", bd=0, cursor="hand2", command=save_changes).pack(side="left", padx=(0, 6))
        tk.Button(button_frame, text="Annulla", bg="#d1d5db", fg=FG, padx=16, pady=6,
                 relief="flat", bd=0, cursor="hand2", command=edit_win.destroy).pack(side="left")
        
        edit_win.columnconfigure(1, weight=1)
    
    def edit_race(self):
        """Modifica metadati della gara selezionata"""
        idx = self.race_listbox.curselection()
        if not idx:
            messagebox.showwarning("Attenzione", "Seleziona una gara prima")
            return
        
        slug, data = self.filtered_races[idx[0]]
        self.open_add_race_form(data.copy(), is_new=False, original_slug=slug)
    
    
    def delete_race(self):
        """Elimina race"""
        idx = self.race_listbox.curselection()
        if not idx:
            messagebox.showwarning("Attenzione", "Seleziona una gara prima")
            return
        
        slug, data = self.filtered_races[idx[0]]
        title = data.get("titolo", slug)
        
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
