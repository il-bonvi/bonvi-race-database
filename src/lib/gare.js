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
// banda arcobaleno/UE), più marcata per i NAT Champ
// (dove la bandiera nazionale è l'identità stessa dell'evento).
export function campionatoFlagOpacity(livello) {
  const opacityMap = {
    'Mondiale': 0.07,
    'Europeo': 0.07,
    'Nazionale': 0.16,           // NAT Champ: la bandiera nazionale è l'identità stessa dell'evento
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

// ── GPX: risoluzione dei riferimenti ─────────────────────────────────────────
// Una gara/tappa può riusare il tracciato di un'altra (campo gpx_reference).
// Il riferimento deve puntare alla sorgente reale del tracciato; se per qualche
// motivo punta a una gara/tappa che a sua volta è solo un riferimento (catena),
// la si segue fino in fondo invece di cercare un file -gpx.json che non esiste.
// bySlug: Map o oggetto { slug: dettagli }
export function resolveGpxSlug(slug, bySlug) {
  const lookup = (k) => (bySlug instanceof Map ? bySlug.get(k) : bySlug?.[k]);
  const seen = new Set();
  let cur = slug;
  while (cur && !seen.has(cur)) {
    seen.add(cur);
    const next = lookup(cur)?.gpx_reference;
    if (!next) break;
    cur = next;
  }
  return cur;
}


// ── Campionati nazionali (NAT Champ) ─────────────────────────────────────────
// A differenza di Mondiali/Europei NON sono un contenitore con più prove: ogni
// prova è una gara autonoma (sedi e mesi diversi), marcata con
//   livello: "Nazionale"  +  paese: <codice ISO>   (es. "it")
// Il recap per nazione/anno si ricava raggruppando queste gare, senza
// contenitore da mantenere.
export const NAT_LIVELLO = 'Nazionale';
export const NAT_LABEL = 'NAT Champ';

export function isNatChamp(gara) {
  return gara?.livello === NAT_LIVELLO && gara?.tipo !== 'campionato';
}

// Codice ISO → nome paese (italiano). Stessi paesi di PAESI_BANDIERA in generator/race_utils.py
const PAESE_NOMI = {
  it: 'Italia', ca: 'Canada', si: 'Slovenia', fr: 'Francia', es: 'Spagna',
  be: 'Belgio', nl: 'Paesi Bassi', ch: 'Svizzera', de: 'Germania', at: 'Austria',
  pt: 'Portogallo', gb: 'Regno Unito', rw: 'Ruanda', au: 'Australia',
  us: 'Stati Uniti', dk: 'Danimarca', no: 'Norvegia', se: 'Svezia', pl: 'Polonia',
  cz: 'Repubblica Ceca', sk: 'Slovacchia', hr: 'Croazia', hu: 'Ungheria',
  co: 'Colombia', jp: 'Giappone', qa: 'Qatar', ae: 'Emirati Arabi Uniti',
};

export function paeseNome(code) {
  if (!code) return '';
  return PAESE_NOMI[String(code).toLowerCase()] ?? String(code).toUpperCase();
}

// Range di date di una gara/contenitore: { start, end } (end = null se giorno singolo).
// - corsa a tappe: data_inizio/data_fine
// - campionato (Mondiale/Europeo): dalle date reali delle prove (il JSON non ha un range
//   inserito a mano, che con prove a giorni/mesi diversi sarebbe da tenere aggiornato)
// - gara singola: solo la data
export function dateRange(gara) {
  let start = gara?.data_inizio || gara?.data || null;
  let end = gara?.data_fine || null;
  if (gara?.tipo === 'campionato' && Array.isArray(gara.tappe) && gara.tappe.length > 0) {
    const ds = gara.tappe.map((t) => t.data).filter(Boolean).sort();
    if (ds.length > 0) { start = ds[0]; end = ds[ds.length - 1]; }
  }
  if (!end || end === start) end = null;
  return { start, end };
}

// Formatta un range: "24–25 set" (stesso mese) oppure "30 mag – 07 giu"; giorno singolo se end è null
export function formatDateRange(range) {
  if (!range?.start) return '—';
  if (!range.end) return formatData(range.start);
  const a = new Date(range.start);
  const b = new Date(range.end);
  if (a.getUTCFullYear() === b.getUTCFullYear() && a.getUTCMonth() === b.getUTCMonth()) {
    const dd = (d) => String(d.getUTCDate()).padStart(2, '0');
    const mon = b.toLocaleDateString('it-IT', { month: 'short', timeZone: 'UTC' });
    return `${dd(a)}–${dd(b)} ${mon}`;
  }
  return `${formatData(range.start)} – ${formatData(range.end)}`;
}



// ── Nome fisso e sigla delle prove dei campionati (Mondiale/Europeo) ─────────
// Le prove NON hanno un nome libero: seguono sempre il pattern
//   nome:  <genere><categoria> <disciplina>   es. "WJ Road Race", "WJ ITT", "WJ Mixed Relay"
//   sigla: <genere><categoria><disciplina>    es. "WJRR", "WJITT", "WJMR"
// Genere: W donne, M uomini, X misto (prove senza genere, es. Mixed Relay).
// Categoria: E Elite, U U23, J Junior, A Allievi.
// ⚠ Tenere in sync con le stesse tabelle in generator/race_utils.py (prova_nome / prova_sigla).
const GENERE_CODICE = { Femminile: 'W', Maschile: 'M' };
const CATEGORIA_CODICE = { Elite: 'E', U23: 'U', Junior: 'J', Allievi: 'A' };
const DISCIPLINA_CODICE = {
  Strada: 'RR', ITT: 'ITT', TTT: 'TTT', Criterium: 'CRIT', 'Mixed Relay': 'MR', 'Tipo pista': 'TP',
};
const DISCIPLINA_NOME = {
  Strada: 'Road Race', ITT: 'ITT', TTT: 'TTT', Criterium: 'Criterium', 'Mixed Relay': 'Mixed Relay', 'Tipo pista': 'Track Format',
};

function provaPrefisso(prova) {
  const cats = Array.isArray(prova?.categoria) ? prova.categoria : (prova?.categoria ? [prova.categoria] : []);
  const codCat = cats.map((c) => CATEGORIA_CODICE[c] ?? '').join('');
  if (!codCat) return ''; // prova incompleta (categoria mancante): solo disciplina
  return (GENERE_CODICE[prova?.genere] ?? 'X') + codCat;
}

// prova: { genere, categoria, disciplina } (una tappa di campionato, meta o dettagli)
export function provaNome(prova) {
  const disc = DISCIPLINA_NOME[prova?.disciplina] ?? prova?.disciplina ?? '';
  return `${provaPrefisso(prova)} ${disc}`.trim();
}

export function provaSigla(prova) {
  const disc = DISCIPLINA_CODICE[prova?.disciplina] ?? String(prova?.disciplina ?? '').toUpperCase();
  return `${provaPrefisso(prova)}${disc}`;
}

// ── Ordine fisso delle prove di un campionato (navigazione in topbar) ────────
// NON cronologico: categoria dall'alto in basso (Elite → U23 → Junior → Allievi),
// poi disciplina RR → ITT → TTT → Mixed Relay (Criterium e Tipo pista in coda),
// a parità di entrambe prima le donne poi gli uomini (prove miste per ultime).
// Es.: Elite RR, Elite ITT, Elite Mixed Relay, U23 RR, U23 ITT, ...
const CATEGORIA_ORDINE = ['Elite', 'U23', 'Junior', 'Allievi'];
const DISCIPLINA_ORDINE = ['Strada', 'ITT', 'TTT', 'Mixed Relay', 'Criterium', 'Tipo pista'];
const GENERE_ORDINE = ['Femminile', 'Maschile'];

const rango = (lista, valore) => {
  const i = lista.indexOf(valore);
  return i === -1 ? lista.length : i;
};

// prova: { genere, categoria, disciplina } — categoria può essere stringa o array
export function compareProve(a, b) {
  const cats = (p) => (Array.isArray(p?.categoria) ? p.categoria : (p?.categoria ? [p.categoria] : []));
  const rangoCat = (p) => Math.min(...cats(p).map((c) => rango(CATEGORIA_ORDINE, c)), CATEGORIA_ORDINE.length);
  return (
    rangoCat(a) - rangoCat(b) ||
    rango(DISCIPLINA_ORDINE, a?.disciplina) - rango(DISCIPLINA_ORDINE, b?.disciplina) ||
    rango(GENERE_ORDINE, a?.genere) - rango(GENERE_ORDINE, b?.genere)
  );
}
