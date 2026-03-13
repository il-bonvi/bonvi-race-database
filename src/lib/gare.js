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
export const CATEGORIE = ['Elite', 'U23', 'Junior', 'Allievi'];
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
   *   - "Elite" → PRO
   *   - "U23" → U
   *   - "Junior" → J
   *   - "Allievi" → A
   * 
   * Esempio: getCategoriaCode("Femminile", "Elite") → "DPRO"
   */
  const genereMap = {
    'Maschile': 'M',
    'Femminile': 'D'
  };
  
  const categoriaMap = {
    'Elite': 'PRO',
    'U23': 'U',
    'Junior': 'J',
    'Allievi': 'A'
  };
  
  const genereCode = genereMap[genere] || '';
  const catCode = categoriaMap[categoria] || '';
  
  return genereCode && catCode ? `${genereCode}${catCode}` : '';
}

export function categoriaColor(categoria) {
  const colorMap = {
    'Elite':    '#E91E63',
    'U23':      '#1B2ACF',
    'Junior':   '#28B534',
    'Allievi':  '#FFC107',
  };
  
  // Gestisci sia string che array
  if (!Array.isArray(categoria)) {
    return colorMap[categoria] ?? '#888';
  }
  
  // Se è un array singolo, returna il colore diretto
  if (categoria.length === 1) {
    return colorMap[categoria[0]] ?? '#888';
  }
  
  // Se sono multiple categorie, crea un gradiente
  const colors = categoria.map(cat => colorMap[cat] ?? '#888');
  return `linear-gradient(90deg, ${colors.join(', ')})`;
}

export function disciplinaIcon(disciplina) {
  return {
    'Strada':     '↗',
    'Criterium':  '⟳',
    'ITT':        '⏱',
    'TTT':        '⏱⏱',
    'Tipo pista': '◯',
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
