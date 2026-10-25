// Types and calls for muthur's JSON API (src/muthur/web.py).

export type PathState = { path: string; exists: boolean; readable: boolean; writable: boolean };
export type Job = { name: string; started: number; finished: number | null; done: number; total: number; error: string | null; running: boolean };
export type KodiState = { connected: true; version: string } | { connected: false; problem: string };

export type Status = {
  version: string;
  applying: boolean;
  tmdb: { configured: boolean };
  kodi: KodiState | null;
  paths: { downloads: PathState; tv: PathState; film: PathState };
  inbox: { counts: Partial<Record<ItemStatus, number>>; scannedAt: number | null };
  memory: { shows: number };
  job: Job | null;
};

export type ItemStatus = 'ready' | 'review' | 'ignored' | 'waiting' | 'suspicious' | 'packed' | 'error';
export type Problem = 'missing' | 'unnumbered' | 'other-episode' | 'exists';
export type Suggestion = { season: number; episode: number; title: string; part: number | null };
export type Planned = {
  source: string; size: number; target: string | null; library: 'TV' | 'Film' | null; writes: string[];
  season?: number | null; episodes?: number[]; tmdb_season?: number | null; tmdb_episode?: number | null; title?: string | null;
  problem?: Problem | null; suggestion?: Suggestion | null;
  parsed?: { season: number | null; episodes: number[]; episodeTitle: string | null; part: number | null; damaged: boolean };
};
export type Candidate = {
  tmdbId: number; title: string; originalTitle: string; year: number | null; score: number; signals: Record<string, number>;
  poster?: string | null; overview?: string | null;
};
export type Item = {
  id: string; status: ItemStatus; reason: string; kind: 'tv' | 'movie' | null; title: string | null; year: number | null;
  tmdb_id: number | null; known: boolean; chosen?: boolean; parsed?: { title: string | null; year: number | null };
  files: Planned[]; candidates: Candidate[]; notes: string[]; size: number;
};
export type Kind = 'tv' | 'movie';
// A title on TMDB as Review shows it: from muthur's candidates, a search or a pasted link.
export type Card = { kind: Kind; tmdbId: number; title: string; originalTitle: string; year: number | null; overview: string; poster: string | null; signals?: Record<string, number> };
export type EpisodeChoice = { season: number; episode: number; part: number | null; number: 'file' | 'tmdb' };
export type Choice = { kind: Kind; tmdbId: number; episodes?: Record<string, EpisodeChoice> };
export type Season = {
  seasons: { season: number; name: string | null; episodes: number }[];
  episodes: { episode: number; title: string | null; aired: string | null; runtime: number | null; overview: string | null; still: string | null }[];
};
export type Inbox = { items: Item[]; scannedAt: number | null; job: Job | null };

export type Settings = {
  kodi: { host: string; port: number; user: string; passwordSet: boolean };
  tmdb: { tokenSet: boolean };
  titles: { keepOriginal: string[] };
  paths: { downloads: string; tv: string; film: string };
};

export type ApplyResult = { id: string; ok: boolean; files?: number; why?: string };
export type Run = {
  id: number; kind: string; started: number; finished: number | null; undone: number | null;
  summary: { applied: number; stopped: number; items: ApplyResult[] } | null;
  counts: { move: number; write: number; quarantine: number; mkdir: number };
};
export type Op = { id: number; item: string; op: 'mkdir' | 'move' | 'write' | 'quarantine'; src: string | null; dst: string; size: number | null; status: 'done' | 'undone' | 'failed'; error: string | null };

export class ApiError extends Error {}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...init });
  if (!r.ok) {
    let message = `The server answered with an error (${r.status}).`;
    try {
      const body = await r.json();
      if (typeof body.detail === 'string') message = body.detail;
    } catch {
      // keep the generic message
    }
    throw new ApiError(message);
  }
  return r.json() as Promise<T>;
}

export const api = {
  status: () => call<Status>('/api/status'),
  inbox: () => call<Inbox>('/api/inbox'),
  scan: () => call<Job>('/api/inbox/scan', { method: 'POST' }),
  learnShows: () => call<Job>('/api/memory/import', { method: 'POST' }),
  job: () => call<Job | null>('/api/jobs/current'),
  settings: () => call<Settings>('/api/settings'),
  saveSettings: (body: unknown) => call<Settings>('/api/settings', { method: 'PUT', body: JSON.stringify(body) }),
  testKodi: () => call<KodiState>('/api/kodi/test', { method: 'POST' }),
  scanKodi: () => call<{ started: boolean }>('/api/kodi/scan', { method: 'POST' }),
  apply: (ids?: string[]) => call<Job>('/api/apply', { method: 'POST', body: JSON.stringify(ids ? { ids } : {}) }),
  history: () => call<{ runs: Run[] }>('/api/history'),
  run: (id: number) => call<{ ops: Op[] }>(`/api/history/${id}`),
  undo: (id: number) => call<Job>(`/api/history/${id}/undo`, { method: 'POST', body: '{}' }),
  search: (kind: Kind, q: string, year?: number) =>
    call<{ results: Card[] }>(`/api/tmdb/search?${new URLSearchParams({ kind, q, ...(year ? { year: String(year) } : {}) })}`),
  resolve: (link: string) => call<Card>('/api/tmdb/resolve', { method: 'POST', body: JSON.stringify({ link }) }),
  season: (tvId: number, season: number) => call<Season>(`/api/tmdb/tv/${tvId}/season/${season}`),
  preview: (id: string, choice: Choice) => call<Item>('/api/review/preview', { method: 'POST', body: JSON.stringify({ id, choice }) }),
  choose: (id: string, choice: Choice, remember: boolean) =>
    call<Item>('/api/review/choose', { method: 'POST', body: JSON.stringify({ id, choice, remember }) }),
  forget: (id: string) => call<Item>('/api/review/forget', { method: 'POST', body: JSON.stringify({ id }) }),
};
