#!/usr/bin/env python3
"""
genera_report.py — Aggiungi nuova race al database da file GPX.

Uso:
    python generator/genera_report.py                  # dialog interattivo con selezione file
    python generator/genera_report.py percorso.gpx     # salta selezione, usa il file indicato

Per GESTIRE (list, edit, delete) le gare, usa:
    python generator/gestisci_gare.py              # UI completa per gestione database

Lo script:
  1. Seleziona file GPX (da dialogo o riga di comando)
  2. Estrae distanza, dislivello, punti GPS dal GPX
  3. Mostra form interattivo per compilare metadati (titolo, slug, data, etc)
  4. Crea JSON → gare-sorgenti/<slug>.json (database Astro)
  5. Copia JSON → public/gare-sorgenti/<slug>.json (servito al browser per gara.html)

Visualizzazione:
  La gara viene visualizzata in /gare/<slug>/ con:
  - Top-bar Astro (navigazione, metadati)
  - Iframe che carica /gara.html?gara=<slug> (HTML originale con mappa, altimetria, Street View)

Pubblicazione:
    git add .
    git commit -m "Aggiungi gara: <titolo>"
    git push
"""

import sys
import re
import json
import argparse
import logging
from pathlib import Path
from datetime import date, datetime

from race_utils import (
    CATEGORIE,
    GENERI,
    DISCIPLINE,
    slugify,
    categoria_code,
    get_slug_suffix,
    parse_gpx,
    reverse_geocode,
    update_gares_index,
    validate_date_string,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ── CONFIGURAZIONE ────────────────────────────────────────────────────────────
ARCHIVIO_DIR = Path(__file__).parent.parent
# ─────────────────────────────────────────────────────────────────────────────


def _update_index():
    """Wrapper locale — delega a race_utils con i path del progetto."""
    update_gares_index(
        gare_dir=ARCHIVIO_DIR / "gare-sorgenti" / "dettagli",
        archivio_dir=ARCHIVIO_DIR,
    )


# ── CALENDARIO POPUP ─────────────────────────────────────────────────────────

def _show_calendar(parent, target_entry, BG, ACCENT, FG, on_date_selected=None):
    """Mini calendario popup. Scrive la data selezionata in target_entry."""
    import tkinter as tk
    import calendar as cal_mod
    from datetime import date as date_cls

    # Leggi data iniziale dall'entry
    try:
        parts = target_entry.get().split("-")
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

    # ── header navigazione ──
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

    # ── griglia giorni ──
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

        # Prima cella: weekday del 1° del mese (0=lun)
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
        target_entry.delete(0, "end")
        target_entry.insert(0, chosen)
        if on_date_selected:
            on_date_selected()
        top.destroy()

    refresh()


# ── DIALOG METADATI ───────────────────────────────────────────────────────────

def ask_metadata(default_title: str, gpx_path_initial: Path, gpx_data: dict, luogo_iniziale: str = "") -> tuple | None:
    """Ritorna (meta_dict, gpx_path) oppure None se annullato."""
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog

    result = {}
    # gpx_path è mutabile dentro la closure tramite lista
    current_gpx = [gpx_path_initial]

    root = tk.Tk()
    root.title("Aggiungi al database gare")
    root.resizable(False, False)
    root.attributes('-topmost', True)

    BG = "#f5f2ed"; FG = "#0f0f0f"; ACCENT = "#d4401a"
    FONT_LABEL = ("Helvetica", 10, "bold")
    FONT_ENTRY = ("Helvetica", 11)

    root.configure(bg=BG)

    tk.Frame(root, bg=ACCENT, height=4).pack(fill="x")

    # Header con nome GPX e bottone cambio
    header_frame = tk.Frame(root, bg=BG, padx=24)
    header_frame.pack(fill="x", pady=(8, 0))

    gpx_label = tk.Label(header_frame,
                         text=f"GPX: {gpx_path_initial.name}",
                         font=("Helvetica", 9), bg=BG, fg="#7a746b", anchor="w")
    gpx_label.pack(side="left")

    raw_km = gpx_data.get("distanza_km")
    raw_d  = gpx_data.get("dislivello_m")

    def cambia_gpx():
        nonlocal raw_km, raw_d
        new_path = filedialog.askopenfilename(
            parent=root,
            title="Seleziona nuovo file GPX",
            filetypes=[("GPX files", "*.gpx"), ("All files", "*.*")]
        )
        if not new_path:
            return
        new_path = Path(new_path)
        current_gpx[0] = new_path
        gpx_label.config(text=f"GPX: {new_path.name}")

        # Rileggi distanza e dislivello
        new_data = parse_gpx(new_path)
        nonlocal raw_km, raw_d
        raw_km = new_data.get("distanza_km")
        raw_d  = new_data.get("dislivello_m")

        # Aggiorna campi km e D+
        g = 1
        try: g = int(giri_var.get())
        except: pass
        e_km.delete(0, tk.END)
        if raw_km: e_km.insert(0, str(round(raw_km * g, 2)))
        e_dp.delete(0, tk.END)
        if raw_d: e_dp.insert(0, str(round(raw_d * g)))

        # Aggiorna luogo tramite geocoding
        lat = new_data.get("center_lat")
        lon = new_data.get("center_lon")
        if lat and lon:
            luogo = reverse_geocode(lat, lon)
            if luogo:
                e_luogo.delete(0, tk.END)
                e_luogo.insert(0, luogo)

        # Aggiorna titolo/slug solo se non modificati manualmente
        if not slug_manual.get():
            e_titolo.delete(0, tk.END)
            e_titolo.insert(0, new_path.stem)
            update_slug()

    tk.Button(header_frame, text="↺ Cambia GPX", font=("Helvetica", 9),
              bg="#ede9e2", fg="#7a746b", relief="flat", bd=0,
              padx=8, pady=3, cursor="hand2",
              command=cambia_gpx).pack(side="right")

    tk.Label(root, text="Aggiungi percorso al database",
             font=("Helvetica", 13, "bold"), bg=BG, fg=FG, pady=8).pack()

    frame = tk.Frame(root, bg=BG, padx=24, pady=4)
    frame.pack(fill="both")
    frame.grid_columnconfigure(0, weight=1)

    def lbl(text, row_n):
        tk.Label(frame, text=text, font=FONT_LABEL, bg=BG, fg="#7a746b",
                 anchor="w").grid(row=row_n*2, column=0, columnspan=2,
                                  sticky="w", pady=(10,1))

    def ent(row_n, val=""):
        e = tk.Entry(frame, font=FONT_ENTRY, bg="white", fg=FG, relief="solid", bd=1)
        e.grid(row=row_n*2+1, column=0, columnspan=2, sticky="ew")
        if val: e.insert(0, str(val))
        return e

    def cmb(row_n, values, default=0):
        c = ttk.Combobox(frame, values=values, state="readonly", font=FONT_ENTRY)
        c.grid(row=row_n*2+1, column=0, columnspan=2, sticky="ew")
        c.current(default)
        return c

    def make_date_field(row_n, initial_val, on_change_callback=None):
        """Entry data + bottone calendario popup."""
        f_row = tk.Frame(frame, bg=BG)
        f_row.grid(row=row_n*2+1, column=0, columnspan=2, sticky="ew")
        f_row.grid_columnconfigure(0, weight=1)
        e = tk.Entry(f_row, font=FONT_ENTRY, bg="white", fg=FG, relief="solid", bd=1)
        e.grid(row=0, column=0, sticky="ew")
        e.insert(0, initial_val)

        def open_cal():
            _show_calendar(root, e, BG, ACCENT, FG, on_date_selected=on_change_callback)

        tk.Button(f_row, text="📅", font=("Helvetica", 11), bg=BG, fg=FG,
                  relief="flat", bd=0, cursor="hand2",
                  command=open_cal).grid(row=0, column=1, padx=(4,0))
        return e

    lbl("Nome gara *", 0);       e_titolo   = ent(0, default_title)
    lbl("Serie *", 1);           e_race_series = ent(1, default_title)
    lbl("Slug URL *", 2);        e_slug     = ent(2)
    
    # Crea placeholder per data (sarà sostituito dopo update_slug)
    f_row_data = tk.Frame(frame, bg=BG)
    f_row_data.grid(row=7, column=0, columnspan=2, sticky="ew")
    f_row_data.grid_columnconfigure(0, weight=1)
    lbl("Data (AAAA-MM-GG) *", 3);
    e_data = tk.Entry(f_row_data, font=FONT_ENTRY, bg="white", fg=FG, relief="solid", bd=1)
    e_data.grid(row=0, column=0, sticky="ew")
    e_data.insert(0, date.today().isoformat())
    btn_cal = tk.Button(f_row_data, text="📅", font=("Helvetica", 11), bg=BG, fg=FG,
                  relief="flat", bd=0, cursor="hand2")
    btn_cal.grid(row=0, column=1, padx=(4,0))
    
    lbl("Genere *", 4);          cb_genere  = cmb(4, GENERI, default=GENERI.index("Femminile"))
    lbl("Categoria *", 5);       cb_cat     = cmb(5, CATEGORIE, default=CATEGORIE.index("Junior"))
    lbl("Disciplina *", 6);      cb_disc    = cmb(6, DISCIPLINE)

    # Auto-slug
    slug_manual = tk.BooleanVar(value=False)
    def update_slug(*_):
        if not slug_manual.get():
            e_slug.delete(0, tk.END)
            titolo_slug = slugify(e_titolo.get())
            # Aggiungi l'anno dalla data allo slug per differenziare le versioni
            data_str = e_data.get().strip()
            year = ""
            if data_str and len(data_str) >= 4:
                year = data_str.split('-')[0]
            
            # Aggiungi il codice categoria allo slug, considerando il flag WT
            genere = cb_genere.get()
            categoria = cb_cat.get()
            is_wt = wt_var.get()
            cat_suffix = get_slug_suffix(genere, categoria, is_wt)
            
            if year:
                slug = f"{titolo_slug}-{year}-{cat_suffix}" if cat_suffix else f"{titolo_slug}-{year}"
            else:
                slug = f"{titolo_slug}-{cat_suffix}" if cat_suffix else titolo_slug
            
            e_slug.insert(0, slug)
    
    # Imposta il comando del bottone calendario
    btn_cal.config(command=lambda: _show_calendar(root, e_data, BG, ACCENT, FG, on_date_selected=lambda: update_slug()))
    
    e_titolo.bind("<KeyRelease>", update_slug)
    e_data.bind("<KeyRelease>", update_slug)
    e_data.bind("<FocusOut>", update_slug)
    cb_genere.bind("<<ComboboxSelected>>", update_slug)
    cb_cat.bind("<<ComboboxSelected>>", update_slug)
    wt_var.trace_add("write", update_slug)
    e_slug.bind("<KeyPress>", lambda e: slug_manual.set(True))
    update_slug()

    # Seconda sezione: stats con giri
    frame2 = tk.Frame(root, bg=BG, padx=24, pady=4)
    frame2.pack(fill="both")
    frame2.grid_columnconfigure(0, weight=1)
    frame2.grid_columnconfigure(1, weight=1)
    frame2.grid_columnconfigure(2, weight=1)

    def lbl2(text, row_n, col, colspan=1):
        tk.Label(frame2, text=text, font=FONT_LABEL, bg=BG, fg="#7a746b",
                 anchor="w").grid(row=row_n*2, column=col, columnspan=colspan,
                                  sticky="w", padx=(0,8), pady=(10,1))

    def ent2(row_n, col, val="", colspan=1):
        e = tk.Entry(frame2, font=FONT_ENTRY, bg="white", fg=FG, relief="solid", bd=1)
        e.grid(row=row_n*2+1, column=col, columnspan=colspan, sticky="ew", padx=(0,8))
        if val != "": e.insert(0, str(val))
        return e

    lbl2("Giri del circuito", 0, 0)
    giri_var = tk.IntVar(value=1)
    spin_giri = tk.Spinbox(frame2, from_=1, to=50, textvariable=giri_var,
                           font=FONT_ENTRY, bg="white", fg=FG, relief="solid", bd=1, width=5)
    spin_giri.grid(row=1, column=0, sticky="w", padx=(0,8))

    lbl2("Distanza (km)", 0, 1)
    e_km = ent2(0, 1, val=raw_km if raw_km else "")

    lbl2("Dislivello (m D+)", 0, 2)
    e_dp = ent2(0, 2, val=raw_d if raw_d else "")

    def update_stats(*_):
        try:
            g = int(giri_var.get())
        except:
            return
        if raw_km:
            e_km.delete(0, tk.END)
            e_km.insert(0, str(round(raw_km * g, 2)))
        if raw_d:
            e_dp.delete(0, tk.END)
            e_dp.insert(0, str(round(raw_d * g)))

    giri_var.trace_add("write", update_stats)

    lbl2("Luogo / Regione", 1, 0, colspan=2)
    e_luogo = ent2(1, 0, val=luogo_iniziale, colspan=2)

    lbl2("Velocità media prevista (km/h)", 2, 0, colspan=1)
    e_velocita = ent2(2, 0, val="40")
    
    # Suggerimenti velocità per disciplina
    def suggest_velocity(*_):
        """Suggerisce velocità media basata su disciplina"""
        disc = cb_disc.get()
        suggestions = {
            "Strada": "35",
            "Criterium": "40",
            "ITT": "32"
        }
        suggested_vel = suggestions.get(disc, "35")
        e_velocita.delete(0, tk.END)
        e_velocita.insert(0, suggested_vel)
    
    # Inizializza con default e collega il callback
    cb_disc.bind("<<ComboboxSelected>>", suggest_velocity)
    suggest_velocity()  # Imposta il valore iniziale

    # Checkbox per WT (World Tour)
    wt_var = tk.BooleanVar(value=False)
    wt_check = tk.Checkbutton(frame2, text="Corsa di categoria WT", variable=wt_var, 
                              bg=BG, fg=FG, font=("Helvetica", 10))
    wt_check.grid(row=3, column=0, sticky="w", padx=(0,8), pady=(4,0))

    tk.Label(frame2, text="Opzioni GPX", font=FONT_LABEL, bg=BG, fg="#7a746b",
             anchor="w").grid(row=3, column=0, columnspan=3, sticky="w", pady=(10,1))
    
    # Checkbox per usare GPX di una gara precedente
    use_existing_gpx_var = tk.BooleanVar(value=False)
    
    def load_existing_races():
        """Carica lista file GPX disponibili in gare-sorgenti/gpx/"""
        gpx_dir = ARCHIVIO_DIR / "gare-sorgenti" / "gpx"
        race_options = []
        if gpx_dir.exists():
            for gpx_file in sorted(gpx_dir.glob("*-gpx.json"), reverse=True):
                gpx_slug = gpx_file.stem[:-4]   # rimuove '-gpx'
                # Prova a leggere il titolo dal file dettagli
                details_file = ARCHIVIO_DIR / "gare-sorgenti" / "dettagli" / f"{gpx_slug}.json"
                label = gpx_slug
                if details_file.exists():
                    try:
                        with open(details_file, 'r', encoding='utf-8') as f:
                            d = json.load(f)
                        titolo = d.get('titolo', gpx_slug)
                        data_g = d.get('data', '')
                        label = f"{titolo} ({data_g})"
                    except Exception:
                        pass
                race_options.append((gpx_slug, label))
        return race_options
    
    existing_races = load_existing_races()
    existing_races_sorted = sorted(existing_races, key=lambda x: x[1], reverse=True)
    existing_slugs = [s for s, _ in existing_races_sorted]
    existing_labels = [l for _, l in existing_races_sorted]
    
    cb_existing_gpx = None
    if existing_races_sorted:
        chk_frame = tk.Frame(frame2, bg=BG)
        chk_frame.grid(row=3, column=0, columnspan=2, sticky="w", padx=(0,8), pady=(4,0))
        
        chk = tk.Checkbutton(chk_frame, text="Usa GPX da gara precedente",
                            variable=use_existing_gpx_var, bg=BG, fg=FG, font=("Helvetica", 10))
        chk.pack(side="left")
        
        tk.Label(frame2, text="", font=FONT_LABEL, bg=BG, fg="#7a746b",
                 anchor="w").grid(row=3, column=2, sticky="w", pady=(10,1))
        cb_existing_gpx = ttk.Combobox(frame2, values=existing_labels, state="readonly", font=FONT_ENTRY)
        cb_existing_gpx.grid(row=3, column=2, sticky="ew", padx=(0,0))
        if existing_labels:
            cb_existing_gpx.current(0)
        
        # Disabilita/abilita combo in base al checkbox
        def toggle_combo(*_):
            cb_existing_gpx.config(state="readonly" if use_existing_gpx_var.get() else "disabled")
        
        use_existing_gpx_var.trace_add("write", toggle_combo)
        toggle_combo()

    tk.Label(frame2, text="Note (opzionali)", font=FONT_LABEL, bg=BG, fg="#7a746b",
             anchor="w").grid(row=4, column=0, columnspan=3, sticky="w", pady=(10,1))
    e_note = tk.Text(frame2, font=FONT_ENTRY, bg="white", fg=FG,
                     relief="solid", bd=1, height=3)
    e_note.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(0,4))

    btn_frame = tk.Frame(root, bg=BG, padx=24, pady=16)
    btn_frame.pack(fill="x")
    cancelled = tk.BooleanVar(value=False)

    def on_ok():
        errors = []
        if not e_titolo.get().strip(): errors.append("Nome gara obbligatorio")
        if not e_race_series.get().strip(): errors.append("Serie obbligatoria")
        if not e_slug.get().strip():   errors.append("Slug obbligatorio")
        if not e_data.get().strip():   errors.append("Data obbligatoria")
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", e_data.get().strip()):
            errors.append("Data nel formato AAAA-MM-GG")
        elif not validate_date_string(e_data.get().strip()):
            errors.append("Data non valida (es. mese o giorno inesistente)")
        if errors:
            messagebox.showerror("Errore", "\n".join(errors), parent=root)
            return

        def num_or_none(s):
            try: return float(s.strip()) if s.strip() else None
            except: return None

        result.update({
            "slug":         slugify(e_slug.get().strip()),
            "titolo":       e_titolo.get().strip(),
            "race_series":  e_race_series.get().strip(),
            "data":         e_data.get().strip(),
            "genere":       cb_genere.get(),
            "categoria":    cb_cat.get(),
            "disciplina":   cb_disc.get(),
            "giri":         int(giri_var.get()),
            "distanza_km":  num_or_none(e_km.get()),
            "dislivello_m": num_or_none(e_dp.get()),
            "velocita_media_kmh": num_or_none(e_velocita.get()),
            "luogo":        e_luogo.get().strip() or None,
            "wt":           wt_var.get(),
            "note":         e_note.get("1.0", tk.END).strip() or None,
        })
        
        # Se user ha scelto di usare GPX da gara precedente, aggiungi il riferimento
        if use_existing_gpx_var.get() and cb_existing_gpx and cb_existing_gpx.get():
            # Il valore selezionato nel combo è nel formato "Titolo (data)"
            # Devo trovare lo slug corrispondente
            selected_label = cb_existing_gpx.get()
            for slug_ref, label in existing_races_sorted:
                if label == selected_label:
                    result["gpx_reference"] = slug_ref
                    break
        
        root.destroy()

    def on_cancel():
        cancelled.set(True)
        root.destroy()

    tk.Button(btn_frame, text="Annulla", font=("Helvetica", 11),
              bg="#ede9e2", fg="#7a746b", relief="flat", bd=0,
              padx=16, pady=8, cursor="hand2",
              command=on_cancel).pack(side="right", padx=(8,0))

    tk.Button(btn_frame, text="Aggiungi al database →", font=("Helvetica", 11, "bold"),
              bg=ACCENT, fg="white", relief="flat", bd=0,
              padx=16, pady=8, cursor="hand2",
              command=on_ok).pack(side="right")

    root.bind("<Return>", lambda e: on_ok())
    root.bind("<Escape>", lambda e: on_cancel())
    root.mainloop()

    if cancelled.get() or not result:
        return None
    return result, current_gpx[0]



# ── SELEZIONE FILE GPX ────────────────────────────────────────────────────────

def pick_gpx_file():
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk(); root.withdraw(); root.attributes('-topmost', True)
    path = filedialog.askopenfilename(
        title='Seleziona file GPX',
        filetypes=[('GPX files', '*.gpx'), ('All files', '*.*')]
    )
    root.destroy()
    return Path(path) if path else None




# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Genera report HTML da GPX')
    parser.add_argument('gpx', nargs='?', default=None, help='Path al file GPX')
    args = parser.parse_args()

    # 1. Seleziona GPX
    if args.gpx:
        gpx_path = Path(args.gpx)
        if not gpx_path.exists():
            sys.exit(f"Errore: file GPX non trovato: {args.gpx}")
    else:
        gpx_path = pick_gpx_file()
        if not gpx_path:
            sys.exit("Nessun file selezionato.")

    # 2. Leggi dati dal GPX
    print(f"[*] Lettura GPX: {gpx_path.name}...")
    gpx_data = parse_gpx(gpx_path)
    if gpx_data['distanza_km']:
        print(f"  Distanza rilevata: {gpx_data['distanza_km']} km")
    if gpx_data['dislivello_m']:
        print(f"  Dislivello rilevato: +{gpx_data['dislivello_m']} m")

    # 2b. Geocoding luogo
    luogo_auto = ""
    lat = gpx_data.get("center_lat")
    lon = gpx_data.get("center_lon")
    if lat and lon:
        print(f"[*] Geocoding ({lat:.4f}, {lon:.4f})...")
        luogo_auto = reverse_geocode(lat, lon) or ""
        if luogo_auto:
            print(f"  Luogo rilevato: {luogo_auto}")
        else:
            print(f"  Geocoding non disponibile (offline?)")

    # 3. Dialog metadati
    res = ask_metadata(gpx_path.stem, gpx_path, gpx_data, luogo_iniziale=luogo_auto)
    if res is None:
        print("Annullato.")
        sys.exit(0)

    meta, gpx_path = res   # gpx_path può essere cambiato dall'utente
    slug  = meta["slug"]
    title = meta["titolo"]

    # 3b. Riprocessa GPX se è stato cambiato
    print(f"[*] Processing GPX finale: {gpx_path.name}...")
    gpx_data = parse_gpx(gpx_path)
    if gpx_data.get('gpx_points'):
        print(f"  {len(gpx_data['gpx_points'])} punti estratti")

    # 4. Cartelle destinazione
    out_json_dir = ARCHIVIO_DIR / "gare-sorgenti" / "dettagli"
    out_json_dir.mkdir(parents=True, exist_ok=True)
    out_gpx_dir  = ARCHIVIO_DIR / "gare-sorgenti" / "gpx"
    out_gpx_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_json_dir / f"{slug}.json"


    # 5. Avvisa se esiste già
    if json_path.exists():
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk(); root.withdraw(); root.attributes('-topmost', True)
        ok = messagebox.askyesno("File esistente",
            f"Esiste già una gara con slug '{slug}'.\nVuoi sovrascriverla?")
        root.destroy()
        if not ok:
            print("Operazione annullata.")
            sys.exit(0)

    # 6. Separa gpx_points dai metadati
    gpx_points = gpx_data.get('gpx_points')
    # NON aggiungere gpx_points ai metadati: vanno nel file -gpx.json separato

    # 7. Salva dettagli JSON (rimuovi None)
    meta_clean = {k: v for k, v in meta.items() if v is not None and k != 'gpx_points'}
    json_str = json.dumps(meta_clean, ensure_ascii=False, indent=2)
    json_path.write_text(json_str, encoding='utf-8')
    print(f"[OK] Dettagli  -> {json_path}")

    # 7b. Salva GPX separato
    if gpx_points:
        gpx_file_data = {"slug": slug, "gpx_points": gpx_points}
        gpx_str = json.dumps(gpx_file_data, ensure_ascii=False, indent=2)
        gpx_path_out = out_gpx_dir / f"{slug}-gpx.json"
        gpx_path_out.write_text(gpx_str, encoding='utf-8')
        print(f"[OK] GPX       -> {gpx_path_out}")
        # Mirror in public/
        public_gpx_dir = ARCHIVIO_DIR / "public" / "gare-sorgenti" / "gpx"
        public_gpx_dir.mkdir(parents=True, exist_ok=True)
        (public_gpx_dir / f"{slug}-gpx.json").write_text(gpx_str, encoding='utf-8')
        print(f"[OK] GPX       -> {public_gpx_dir / (slug + '-gpx.json')}")

    # 7c. Mirror dettagli in public/gare-sorgenti/dettagli/ (servito dal browser per gara.html)
    public_json_dir = ARCHIVIO_DIR / "public" / "gare-sorgenti" / "dettagli"
    public_json_dir.mkdir(parents=True, exist_ok=True)
    public_json_path = public_json_dir / f"{slug}.json"
    public_json_path.write_text(json_str, encoding='utf-8')
    print(f"[OK] Dettagli  -> {public_json_path}")

    # Aggiorna l'indice per la navigazione tra serie
    _update_index()

    print(f"\n[OK] Gara '{title}' aggiunta al database.")
    print("  Per pubblicare sul sito:")
    print(f"    git add .")
    print(f"    git commit -m \"Aggiungi gara: {title}\"")
    print(f"    git push")

    # 8. Popup finale
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk(); root.withdraw(); root.attributes('-topmost', True)
        gpx_line = f"  gare-sorgenti/gpx/{slug}-gpx.json" if gpx_points else "  (nessun GPX caricato)"
        msg = (
            f'"{title}" aggiunta al database!\n\n'
            f'File creati:\n'
            f'  gare-sorgenti/dettagli/{slug}.json\n'
            f'{gpx_line}\n\n'
            f'Per pubblicare sul sito:\n'
            f'  git add .\n'
            f'  git commit -m "Aggiungi gara: {title}"\n'
            f'  git push'
        )
        messagebox.showinfo("Database aggiornato!", msg)
        root.destroy()
    except Exception:
        pass


if __name__ == '__main__':
    main()