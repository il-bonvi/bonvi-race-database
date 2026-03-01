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
from datetime import datetime
from tkinter import ttk
import tkinter as tk
from tkinter import messagebox
from pathlib import Path

ARCHIVIO_DIR = Path(__file__).parent.parent
GARE_DIR = ARCHIVIO_DIR / "gare-sorgenti"
GARE_DIR.mkdir(parents=True, exist_ok=True)


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
    """Salva race JSON nella root (source of truth).
    
    Il file viene copiato automaticamente in public/ durante il build Astro.
    """
    # Imposta race_series automaticamente dal titolo
    if 'titolo' in data:
        data['race_series'] = data['titolo']
    
    json_path = GARE_DIR / f"{slug}.json"
    data_clean = {k: v for k, v in data.items() if v is not None}
    json_str = json.dumps(data_clean, ensure_ascii=False, indent=2)
    
    json_path.write_text(json_str, encoding='utf-8')
    
    # Aggiorna l'indice per la navigazione tra serie
    update_gares_index()


def delete_race(slug: str):
    """Elimina race dalla root (source of truth).
    
    Il file viene rimosso automaticamente da public/ durante il build Astro.
    """
    json_path = GARE_DIR / f"{slug}.json"
    if json_path.exists():
        json_path.unlink()
    
    # Aggiorna l'indice per la navigazione tra serie
    update_gares_index()


def git_push_changes(message: str = None) -> tuple:
    """Esegue git add, commit e push automatico.
    
    Returns:
        (success: bool, message: str)
    """
    import subprocess
    
    try:
        # git add
        subprocess.run(
            ["git", "add", "."],
            cwd=ARCHIVIO_DIR,
            capture_output=True,
            text=True,
            check=True
        )
        
        # git commit (con messaggio di default se non fornito)
        if not message:
            message = f"Update races database - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        
        result = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=ARCHIVIO_DIR,
            capture_output=True,
            text=True
        )
        
        # Se non c'è nulla da committare, va bene comunque
        if result.returncode != 0 and "nothing to commit" not in result.stdout:
            return False, f"Errore commit: {result.stderr}"
        
        # git push
        result = subprocess.run(
            ["git", "push"],
            cwd=ARCHIVIO_DIR,
            capture_output=True,
            text=True,
            check=True
        )
        
        return True, "Push completato con successo!"
        
    except subprocess.CalledProcessError as e:
        return False, f"Errore git: {e.stderr}"
    except FileNotFoundError:
        return False, "Git non trovato. Assicurati che git sia installato."
    except Exception as e:
        return False, f"Errore inaspettato: {str(e)}"


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
                if data.get('categoria') != self.filter_state['categoria']:
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
CATEGORIA:    {data.get('categoria', '—')}
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
        """Chiama genera_report.py"""
        import subprocess
        try:
            subprocess.run([sys.executable, str(ARCHIVIO_DIR / "generator" / "genera_report.py")], check=False)
            self.refresh_list()
        except Exception as e:
            messagebox.showerror("Errore", f"Impossibile aggiungere gara: {e}")
    
    def edit_race(self):
        """Modifica metadati"""
        idx = self.race_listbox.curselection()
        if not idx:
            messagebox.showwarning("Attenzione", "Seleziona una gara prima")
            return
        
        slug, data = self.filtered_races[idx[0]]
        
        edit_win = tk.Toplevel(self.root)
        edit_win.title(f"Modifica: {data.get('titolo', slug)}")
        edit_win.geometry("500x650")
        edit_win.configure(bg=BG)
        
        # Calcolo valori raw (per singolo giro) dai dati attuali
        giri_iniziali = max(1, int(data.get('giri', 1)))
        km_iniziale = float(data.get('distanza_km', 0)) or 0
        dislivello_iniziale = float(data.get('dislivello_m', 0)) or 0
        km_raw = km_iniziale / giri_iniziali if giri_iniziali > 0 else 0
        dislivello_raw = dislivello_iniziale / giri_iniziali if giri_iniziali > 0 else 0
        
        fields = [
            ("titolo", "Titolo", "entry"),
            ("data", "Data (AAAA-MM-GG)", "entry"),
            ("luogo", "Luogo", "entry"),
            ("giri", "Giri del circuito", "spinner"),  # Nuovo campo
            ("distanza_km", "Distanza (km)", "entry"),
            ("dislivello_m", "Dislivello (m)", "entry"),
            ("velocita_media_kmh", "Velocità media prevista (km/h)", "entry"),
            ("genere", "Genere", "combo", GENERI),
            ("categoria", "Categoria", "combo", CATEGORIE),
            ("disciplina", "Disciplina", "combo", DISCIPLINE),
        ]
        
        entries = {}
        
        for i, field_info in enumerate(fields):
            key = field_info[0]
            label = field_info[1]
            widget_type = field_info[2]
            
            tk.Label(edit_win, text=label, font=("Helvetica", 10, "bold"), bg=BG).grid(
                row=i, column=0, sticky="w", padx=12, pady=6)
            
            if widget_type == "spinner":
                # Spinbox per giri del circuito
                var = tk.IntVar(value=data.get(key, 1))
                spinner = tk.Spinbox(edit_win, from_=1, to=50, textvariable=var,
                                   font=("Helvetica", 10), width=10)
                spinner.grid(row=i, column=1, sticky="w", padx=12, pady=6)
                entries[key] = var
                
                # Binding: quando cambia giri, aggiorna km e dislivello
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
                
            elif widget_type == "combo":
                options = field_info[3]
                var = tk.StringVar(value=data.get(key, ""))
                combo = tk.OptionMenu(edit_win, var, *options)
                combo.config(width=30)
                combo.grid(row=i, column=1, sticky="ew", padx=12, pady=6)
                entries[key] = var
            else:
                entry = tk.Entry(edit_win, width=35, font=("Helvetica", 10))
                # Tutti i campi editabili
                entry.insert(0, str(data.get(key, "") or ""))
                entry.grid(row=i, column=1, sticky="ew", padx=12, pady=6)
                entries[key] = entry
        
        def save_changes():
            for key, widget in entries.items():
                if hasattr(widget, 'cget') and widget.cget('state') == 'readonly':
                    # Per i campi readonly, leggi il valore come è
                    val = widget.get()
                else:
                    val = widget.get() if hasattr(widget, 'get') else widget
                
                if key in ("distanza_km", "dislivello_m", "giri", "velocita_media_kmh"):
                    try:
                        if key == "giri":
                            val = int(val) if val else 1
                        else:
                            val = float(val) if val else None
                    except:
                        val = None
                data[key] = val
            
            save_race(slug, data)
            messagebox.showinfo("Salvato", "Gara modificata con successo")
            self.refresh_list()
            edit_win.destroy()
        
        row_button = len(fields)
        button_frame = tk.Frame(edit_win, bg=BG)
        button_frame.grid(row=row_button, column=0, columnspan=2, sticky="ew", padx=12, pady=12)
        
        tk.Button(button_frame, text="Salva", bg=ACCENT, fg="white", padx=16, pady=6,
                 relief="flat", bd=0, cursor="hand2", command=save_changes).pack(side="left", padx=(0, 6))
        tk.Button(button_frame, text="Annulla", bg="#d1d5db", fg=FG, padx=16, pady=6,
                 relief="flat", bd=0, cursor="hand2", command=edit_win.destroy).pack(side="left")
        
        edit_win.columnconfigure(1, weight=1)
    
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
