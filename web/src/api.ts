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
export type Planned = { source: string; size: number; target: string | null; library: 'TV' | 'Film' | null; writes: string[] };
export type Candidate = { tmdbId: number; title: string; originalTitle: string; year: number | null; score: number; signals: Record<string, number> };
export type Item = {
  id: string; status: ItemStatus; reason: string; kind: 'tv' | 'movie' | null; title: string | null; year: number | null;
  tmdb_id: number | null; known: boolean; files: Planned[]; candidates: Candidate[]; notes: string[]; size: number;
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
  apply: (ids?: string[]) => call<Job>('/api/apply', { method: 'POST', body: JSON.stringify(ids ? { ids } : {}) }),
  history: () => call<{ runs: Run[] }>('/api/history'),
  run: (id: number) => call<{ ops: Op[] }>(`/api/history/${id}`),
  undo: (id: number) => call<Job>(`/api/history/${id}/undo`, { method: 'POST', body: '{}' }),
};
