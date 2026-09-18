// ── Colori: unica fonte di verità per tutto il sito ─────────────────────────
// Ogni pagina/componente deve importare queste costanti invece di ridefinire
// i colori localmente — altrimenti un cambio colore va ripetuto a mano in
// più file e si rischia di dimenticarne qualcuno (già successo una volta).
export const WT_COLOR = '#8A2BE2';

export const CATEGORIA_COLORS = {
  'Elite':    '#E91E63',
  'U23':      '#1B2ACF',
  'Junior':   '#28B534',
  'Allievi':  '#ffa601',
};

// Colori delle tracce dei campionati su BMAP: non derivano da CAMPIONATO_THEME
// (pensato per badge/bordi su sfondo chiaro) perché lì serve visibilità sulla
// mappa (stile scuro di default) e distinzione dai colori di categoria.
export const CAMPIONATO_MAP_COLORS = {
  Mondiale: '#ffffff',
  Europeo:  '#0EA5E9',
};

export function formatData(dateStr) {
  if (!dateStr) return '—';
  const d = new Date(dateStr);
  return d.toLocaleDateString('it-IT', { day: '2-digit', month: 'short' });
}

export function formatDistanza(km) {
  if (!km) return '—';
  return Number(km).toFixed(1) + ' km';
}

export function formatDislivello(m) {
  if (!m) return '—';
  return '+' + Math.round(m) + ' m';
}

export const GENERI = ['Maschile', 'Femminile'];
export const CATEGORIE = ['WT', 'Elite', 'U23', 'Junior', 'Allievi'];
export const DISCIPLINE = ['Strada', 'Criterium', 'ITT', 'TTT', 'Tipo pista'];

export function getCategoriaCode(genere, categoria) {
  /**
   * Genera il codice categoria combinando genere e categoria.
   * 
   * Genere:
   *   - "Maschile" → M
   *   - "Femminile" → D
   * 
   * Categoria:
   *   - "Elite" → ELI
   *   - "U23" → U
   *   - "Junior" → J
   *   - "Allievi" → A
   * 
   * Esempio: getCategoriaCode("Femminile", "Elite") → "DELI"
   */
  const genereMap = {
    'Maschile': 'M',
    'Femminile': 'D'
  };
  
  const categoriaMap = {
    'Elite': 'ELI',
    'U23': 'U',
    'Junior': 'J',
    'Allievi': 'A'
  };
  
  const genereCode = genereMap[genere] || '';
  const catCode = categoriaMap[categoria] || '';
  
  return genereCode && catCode ? `${genereCode}${catCode}` : '';
}

export function categoriaColor(categoria) {
  // Gestisci sia string che array
  if (!Array.isArray(categoria)) {
    return CATEGORIA_COLORS[categoria] ?? '#888';
  }
  
  // Se è un array singolo, returna il colore diretto
  if (categoria.length === 1) {
    return CATEGORIA_COLORS[categoria[0]] ?? '#888';
  }
  
  // Se sono multiple categorie, crea un gradiente
  const colors = categoria.map(cat => CATEGORIA_COLORS[cat] ?? '#888');
  return `linear-gradient(90deg, ${colors.join(', ')})`;
}

export function getRaceColor(raceData) {
  /**
   * Ritorna il colore della gara considerando sia il flag WT che la categoria.
   * Se wt=true, ritorna il colore WT (#8A2BE2)
   * Altrimenti usa categoriaColor()
   */
  if (raceData?.wt === true) {
    return WT_COLOR;
  }
  return categoriaColor(raceData?.categoria);
}

export function getRaceColorForBorder(raceData) {
  /**
   * Ritorna il colore/gradiente per il bordo della card
   * Se wt=true, ritorna un colore solido WT
   * Altrimenti calcola il colore dalla categoria
   */
  if (raceData?.wt === true) {
    return WT_COLOR;
  }
  
  const categoria = raceData?.categoria;
  
  if (!Array.isArray(categoria)) {
    return CATEGORIA_COLORS[categoria] ?? '#888';
  }
  
  if (categoria.length === 1) {
    return CATEGORIA_COLORS[categoria[0]] ?? '#888';
  }
  
  const colors = categoria.map(cat => CATEGORIA_COLORS[cat] ?? '#888');
  return `linear-gradient(90deg, ${colors.join(', ')})`;
}

// ── Campionati (Mondiali / Europei / futuri: Nazionali, Olimpiadi) ──────────
export const LIVELLI_CAMPIONATO = ['Mondiale', 'Europeo'];

// Tema colore/skin per livello di campionato, sul modello delle maglie ufficiali
export const CAMPIONATO_THEME = {
  'Mondiale': {
    // bande maglia iridata UCI
    gradient: 'linear-gradient(90deg, #009BDD 0%, #E30613 25%, #1A1A1A 50%, #FFD500 75%, #00954C 100%)',
    accent: '#1A1A1A',
    label: 'Mondiale',
    stars: false,
  },
  'Europeo': {
    // usata per il filo decorativo sottile (card): asimmetrico e spostato
    // a destra — parte già colorata (niente bianco iniziale), un tocco
    // minimo di dorato, una zona bianca ampia spostata verso destra, poi
    // termina in azzurro-blu sul bordo destro. Qui il contrasto testo non
    // è un problema (niente scritte sopra).
    gradient: 'linear-gradient(90deg, #1E5FB8 0%, #3E8FD8 8%, #FFD500 12%, #ffffff 20%, #ffffff 80%, #3E8FD8 92%, #163F7A 100%)',
    // usata per la barra in alto (piena di testo): niente giallo (stona),
    // asimmetrica — bianco solo su un lato, il resto azzurro/blu, mai
    // simmetrica/"squadrata". Il testo ha comunque un'ombra per restare
    // leggibile pure sulle porzioni più chiare.
    barGradient: 'linear-gradient(90deg, #ffffff 0%, #ffffff 5%, #1E5FB8 16%, #4FA8E0 42%, #1E5FB8 68%, #0F2C56 100%)',
    accent: '#1E5FB8',
    label: 'Europeo',
    stars: true,
  },
};

export function campionatoTheme(livello) {
  return CAMPIONATO_THEME[livello] ?? null;
}

// Mappa paese → codice ISO 3166-1 alpha-2, per la bandiera soffusa di sfondo
// dei campionati. Copre i casi più comuni nel ciclismo; l'ultimo pezzo del
// campo "luogo" (dopo l'ultima virgola) viene cercato qui, sia come nome
// paese (italiano/inglese) sia come sigla già pronta (es. "IT", "RW").
const COUNTRY_CODES = {
  'italia': 'it', 'italy': 'it', 'it': 'it',
  'canada': 'ca', 'ca': 'ca',
  'slovenia': 'si', 'si': 'si',
  'francia': 'fr', 'france': 'fr', 'fr': 'fr',
  'spagna': 'es', 'spain': 'es', 'es': 'es',
  'belgio': 'be', 'belgium': 'be', 'be': 'be',
  'olanda': 'nl', 'paesi bassi': 'nl', 'netherlands': 'nl', 'nl': 'nl',
  'svizzera': 'ch', 'switzerland': 'ch', 'ch': 'ch',
  'germania': 'de', 'germany': 'de', 'de': 'de',
  'austria': 'at', 'at': 'at',
  'portogallo': 'pt', 'portugal': 'pt', 'pt': 'pt',
  'regno unito': 'gb', 'gran bretagna': 'gb', 'uk': 'gb', 'united kingdom': 'gb', 'gb': 'gb',
  'ruanda': 'rw', 'rwanda': 'rw', 'rw': 'rw',
  'australia': 'au', 'au': 'au',
  'stati uniti': 'us', 'usa': 'us', 'united states': 'us', 'us': 'us',
  'danimarca': 'dk', 'denmark': 'dk', 'dk': 'dk',
  'norvegia': 'no', 'norway': 'no', 'no': 'no',
  'svezia': 'se', 'sweden': 'se', 'se': 'se',
  'polonia': 'pl', 'poland': 'pl', 'pl': 'pl',
  'repubblica ceca': 'cz', 'czechia': 'cz', 'cz': 'cz',
  'slovacchia': 'sk', 'slovakia': 'sk', 'sk': 'sk',
  'croazia': 'hr', 'croatia': 'hr', 'hr': 'hr',
  'ungheria': 'hu', 'hungary': 'hu', 'hu': 'hu',
  'colombia': 'co', 'co': 'co',
  'giappone': 'jp', 'japan': 'jp', 'jp': 'jp',
  'qatar': 'qa',
  'emirati arabi uniti': 'ae', 'uae': 'ae', 'ae': 'ae',
};

export function countryFlagCode(luogo) {
  if (!luogo) return null;
  const parts = luogo.split(',');
  const last = parts[parts.length - 1]?.trim().toLowerCase();
  if (!last) return null;
  return COUNTRY_CODES[last] ?? null;
}

// Quanto è visibile la bandiera di sfondo: soffusa per i grandi eventi
// internazionali (Mondiale/Europeo, dove l'identità visiva principale è la
// banda arcobaleno/UE), più marcata per un futuro Campionato Italiano
// (dove la bandiera nazionale è l'identità stessa dell'evento).
export function campionatoFlagOpacity(livello) {
  const opacityMap = {
    'Mondiale': 0.07,
    'Europeo': 0.07,
    'Campionato Italiano': 0.16, // non ancora implementato, pronto per quando servirà
  };
  return opacityMap[livello] ?? 0.07;
}

// Colore per il confronto tra prove di uno stesso campionato: la categoria
// resta legata al colore già in uso nel resto del sito (coerenza visiva),
// il genere si distingue con lo stile del tratto (continuo/tratteggiato)
// invece di inventare una nuova scala colori.
export function provaColor(categoria) {
  const cat = Array.isArray(categoria) ? categoria[0] : categoria;
  return CATEGORIA_COLORS[cat] ?? '#888';
}

export function provaDashArray(genere) {
  return genere === 'Femminile' ? '6,5' : null;
}

export function disciplinaIcon(disciplina) {
  return {
    'Strada':     '↗',
    'Criterium':  '⟳',
    'ITT':        '⏱',
    'TTT':        '⏱⏱',
    'Tipo pista': '◯',
    'Mixed Relay': '⚤',
  }[disciplina] ?? '·';
}

export function formatCategoria(categoria, genere) {
  /**
   * Formatta la categoria per il display in italiano.
   * "Allievi" → "allievi" (maschile) o "allieve" (femminile)
   * Altre categorie rimangono invariate.
   * 
   * Parametri:
   *   - categoria: string (es. "Allievi", "Junior", etc.)
   *   - genere: string ("Maschile" o "Femminile")
   * 
   * Ritorna:
   *   - "allievi" se categoria === "Allievi" e genere === "Maschile"
   *   - "allieve" se categoria === "Allievi" e genere === "Femminile"
   *   - categoria invariata per altre categorie
   */
  if (categoria === 'Allievi') {
    return genere === 'Femminile' ? 'Allieve' : 'Allievi';
  }
  return categoria;
}