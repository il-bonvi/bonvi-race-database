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
export const DISCIPLINE = ['Strada', 'Criterium', 'Cronometro'];

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
    'Elite':    '#C8A951',
    'U23':      '#4A7FA5',
    'Junior':   '#5C9E6E',
    'Allievi':  '#A0522D',
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
    'Cronometro': '⏱',
  }[disciplina] ?? '·';
}
