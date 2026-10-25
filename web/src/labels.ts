// Stored values become words for the reader (DESIGN.md §1.7). An unknown value falls back to itself.
import type { ItemStatus } from './api';

export const STATUS: Record<ItemStatus, { label: string; dot: string }> = {
  ready: { label: 'Ready', dot: 'dot-success' },
  review: { label: 'Needs you', dot: 'dot-warning' },
  waiting: { label: 'Still downloading', dot: 'dot-warning' },
  ignored: { label: 'Ignored', dot: '' },
  suspicious: { label: 'Suspicious', dot: 'dot-danger' },
  packed: { label: 'Packed', dot: 'dot-warning' },
  error: { label: "Couldn't read", dot: 'dot-danger' },
};

export const JOBS: Record<string, string> = {
  inbox: 'Checking the downloads',
  memory: 'Learning the shows in your library',
  apply: 'Moving downloads into the library',
  undo: 'Putting a run back',
  scores: 'Refreshing IMDb scores',
};

// Container paths never reach the screen (DESIGN.md §1.6): '/data/TV/x' is shown as 'TV/x'.
export const libraryPath = (p: string | null) => (p ?? '').replace(/^\/data\//, '');

export const SIGNALS: Record<string, string> = {
  title: 'Title', year: 'Year', episodes: 'Episodes exist', runtime: 'Length', country: 'Country', popularity: 'Popularity',
};

const LANGUAGES: Record<string, string> = {
  af: 'Afrikaans', ca: 'Catalan', cs: 'Czech', cy: 'Welsh', da: 'Danish', de: 'German', en: 'English', es: 'Spanish',
  et: 'Estonian', eu: 'Basque', fi: 'Finnish', fr: 'French', ga: 'Irish', gl: 'Galician', hr: 'Croatian', hu: 'Hungarian',
  id: 'Indonesian', is: 'Icelandic', it: 'Italian', lt: 'Lithuanian', lv: 'Latvian', ms: 'Malay', mt: 'Maltese',
  nb: 'Norwegian Bokmål', nl: 'Dutch', nn: 'Norwegian Nynorsk', no: 'Norwegian', pl: 'Polish', pt: 'Portuguese',
  ro: 'Romanian', sk: 'Slovak', sl: 'Slovenian', sq: 'Albanian', sv: 'Swedish', sw: 'Swahili', tl: 'Tagalog',
  tr: 'Turkish', vi: 'Vietnamese', ja: 'Japanese', ko: 'Korean', zh: 'Chinese', ru: 'Russian', el: 'Greek',
  hi: 'Hindi', ar: 'Arabic', he: 'Hebrew', th: 'Thai', uk: 'Ukrainian', fa: 'Persian', bn: 'Bengali', ta: 'Tamil',
};
export const language = (code: string) => LANGUAGES[code] ?? code;
export const ALL_LANGUAGES = Object.keys(LANGUAGES).sort((a, b) => language(a).localeCompare(language(b)));

// File names are cut in the middle: the end (episode, quality, release group) matters most (DESIGN.md §8).
export function middle(text: string, max = 54): string {
  if (text.length <= max) return text;
  const tail = Math.floor((max - 1) * 0.45);
  return `${text.slice(0, max - 1 - tail)}…${text.slice(-tail)}`;
}

// 'tv-sonarr/Some.Show.S01E01…' → name 'Some.Show.S01E01…', folder 'tv-sonarr'.
export function splitId(id: string): { name: string; folder: string | null } {
  const i = id.indexOf('/');
  return i === -1 ? { name: id, folder: null } : { name: id.slice(i + 1), folder: id.slice(0, i) };
}

export function size(bytes: number): string {
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
  if (bytes >= 1e6) return `${Math.round(bytes / 1e6)} MB`;
  return `${Math.max(1, Math.round(bytes / 1e3))} kB`;
}

// "21:14" today, "Sat 24 Oct, 21:14" this year, "24 Oct 2025" before (DESIGN.md §8).
export function when(epochSeconds: number | null): string {
  if (!epochSeconds) return '—';
  const d = new Date(epochSeconds * 1000);
  const now = new Date();
  const time = d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  if (d.toDateString() === now.toDateString()) return time;
  if (d.getFullYear() === now.getFullYear()) {
    return `${d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })}, ${time}`;
  }
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
}
