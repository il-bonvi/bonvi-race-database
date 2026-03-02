export function formatData(dateStr) {
  if (!dateStr) return '—';
  const d = new Date(dateStr);
  return d.toLocaleDateString('it-IT', { day: '2-digit', month: 'short', year: 'numeric' });
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

export function categoriaColor(categoria) {
  // Gestisci sia string che array
  const cat = Array.isArray(categoria) ? categoria[0] : categoria;
  return {
    'Elite':    '#C8A951',
    'U23':      '#4A7FA5',
    'Junior':   '#5C9E6E',
    'Allievi':  '#A0522D',
  }[cat] ?? '#888';
}

export function disciplinaIcon(disciplina) {
  return {
    'Strada':     '↗',
    'Criterium':  '⟳',
    'Cronometro': '⏱',
  }[disciplina] ?? '·';
}
