#!/usr/bin/env python3
"""
Scansiona tutti i JSON in gare-sorgenti/ e genera un index.json
per la navigazione tra le versioni delle stesse serie di gare.
"""

import json
from pathlib import Path

def generate_index():
    gare_dir = Path(__file__).parent.parent / "data" / "gare-sorgenti"
    # Se la directory non esiste, prova il percorso alternativo
    if not gare_dir.exists():
        gare_dir = Path(__file__).parent.parent / "gare-sorgenti"
    
    if not gare_dir.exists():
        print(f"❌ Directory gare-sorgenti non trovata: {gare_dir}")
        return
    
    races = []
    
    # Scansiona tutti i file JSON
    for json_file in sorted(gare_dir.glob("*.json")):
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                gara = json.load(f)
            
            slug = gara.get("slug")
            if not slug:
                print(f"⚠️ {json_file.name}: manca slug")
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
            
        except Exception as e:
            print(f"❌ Errore lettura {json_file.name}: {e}")
    
    # Salva l'index nel pubblico
    index_path = Path(__file__).parent.parent / "public" / "gare-index.json"
    
    try:
        with open(index_path, 'w', encoding='utf-8') as f:
            json.dump(races, f, indent=2, ensure_ascii=False)
        print(f"✅ Index generato: {index_path}")
        print(f"   {len(races)} gare indicizzate")
    except Exception as e:
        print(f"❌ Errore scrittura index: {e}")

if __name__ == "__main__":
    generate_index()
