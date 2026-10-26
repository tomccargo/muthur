// Types and calls for muthur's JSON API (src/muthur/web.py).

export type PathState = { path: string; exists: boolean; readable: boolean; writable: boolean };
export type Job = {
  name: string; started: number; finished: number | null; done: number; total: number; error: string | null; running: boolean;
  step?: string | null;  // the part of a long job running now; done/total count that part
  queued?: boolean;  // waiting for the job before it
};
export type KodiState = ({ connected: true; version: string; sources?: { tv: boolean; film: boolean } } | { connected: false; problem: string; off?: boolean })
  & { pendingScan?: number | null; pendingRefresh?: number; canWake?: boolean };

export type Names = { device: string; nas: string };  // what the reader calls the Kodi box and the NAS

export type Status = {
  version: string;
  names: Names;
  applying: boolean;
  tmdb: { configured: boolean };
  kodi: KodiState | null;
  paths: { downloads: PathState; tv: PathState; film: PathState };
  inbox: { counts: Partial<Record<ItemStatus, number>>; scannedAt: number | null };
  memory: { shows: number };
  watched: {
    last: { at: number; items: number; watched: number; changes: number } | null;
    paused: { at: number; why: string; unwatched: number; items: number } | null;
    live: boolean;  // listening to Kodi's notifications right now
  };
  duplicates: number;
  duplicatesAt: number | null;  // null: never checked
  fixes: number;
  queue: Job[];  // jobs waiting for the current one
  library: { at?: number; imdbData?: number; scores?: number; nfos?: number; leftovers?: number; subtitles?: number; posters?: number; renames?: number; questions?: number };  // from the last library check
  scores: { refreshed: number | null; next: number | null; episodes: number; ratings: number; updated: number | null; checked: number | null };
  job: Job | null;
};

export type ItemStatus = 'ready' | 'review' | 'ignored' | 'waiting' | 'suspicious' | 'packed' | 'error';
export type Problem = 'missing' | 'unnumbered' | 'other-episode' | 'exists' | 'absolute';
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
  kodi: { host: string; port: number; tcpPort: number; user: string; passwordSet: boolean };
  tmdb: { tokenSet: boolean; tokenFrom: 'settings' | 'install' | null; language: string };
  titles: { keepOriginal: string[] };
  downloadStation: { url: string; user: string; passwordSet: boolean };
  dryRun: boolean;
  shield: { enabled: boolean; port: number; app: string };
  quality: { preferHdr: boolean };
  names: Names;
  paths: { downloads: string; tv: string; film: string };
};

export type ApplyResult = { id: string; ok: boolean; files?: number; why?: string };
export type Run = {
  id: number; kind: string; started: number; finished: number | null; undone: number | null;
  // Apply, Duplicates and Inbox runs list their items; Health runs count what was done per kind and list what failed.
  summary: { applied?: number; stopped?: number; items?: ApplyResult[]; done?: Record<string, number>;
    failed?: { path: string; why: string }[]; label?: string } | null;
  counts: { move: number; write: number; quarantine: number; mkdir: number; update: number };
};
export type Op = { id: number; item: string; op: 'mkdir' | 'move' | 'write' | 'quarantine' | 'update'; src: string | null; dst: string; size: number | null; status: 'done' | 'undone' | 'failed'; error: string | null };

// The library index (Library, Duplicates, Health). A score is [source, value, votes].
export type Score = [string, number, number] | null;
export type LibProblems = { noNfo: number; noScore: number; duplicates: number; damaged: number; loose: number };
export type ShowSummary = {
  folder: string; title: string; year: number | null; ids: Record<string, string>; nfo: boolean; poster: boolean; rating: Score;
  count: number; seasons: number; watched: number; size: number; problems: LibProblems;
};
export type LibEpisode = {
  file: string; size: number; season: number | null; episodes: number[]; nfo: boolean; muthur: boolean; title: string | null;
  rating: Score; imdb: [number, number] | null; thumb: boolean; subs: number; subLangs?: string[]; damaged: boolean; sample: boolean; mismatch: boolean;
  watched: number | null; duplicate: boolean;
  renameTo?: string | null;  // the name the library gives it, when that differs
};
export type ShowDetail = Omit<ShowSummary, never> & { episodes: LibEpisode[]; loose: string[]; scoreNotes?: Record<string, string> };
export type Film = {
  key: string; folder: boolean; file: string | null; size: number; others: string[]; title: string; year: number | null;
  ids: Record<string, string>; nfo: boolean; muthur: boolean; rating: Score; imdb: [number, number] | null; poster: boolean;
  flags: string[]; watched: number | null; problems: LibProblems; nfoFile?: string | null;
};
export type Library = { at: number | null; shows: ShowSummary[]; films: Film[] };

export type Copy = {
  path: string; nfo: boolean; muthur: boolean; watched: number | null; folder: boolean; label: string;
  quality: { size: number; readable: boolean; source: string };
};
export type DupOp = { op: 'move' | 'quarantine'; src: string; dst?: string };
export type DupPlan = { final: string; ops: DupOp[] };
export type DupGroup = {
  id: string; kind: 'episode' | 'film'; label: string; title: string; show: string | null; copies: Copy[]; keep: string;
  note: string | null; plan: DupPlan;
};
export type DupResult = { applied: number; stopped: number; items: { id: string; label: string; ok: boolean; why?: string; kodi?: { ok: boolean; why?: string } }[] };

export type FixKind = 'imdb-data' | 'leftovers' | 'empty-films' | 'subtitles' | 'episode-nfos' | 'show-nfos' | 'film-nfos' | 'posters' | 'imdb-scores' | 'renames' | 'film-renames';
export type FixItem = { path: string; label?: string; why?: string; score?: [number, number] };
export type Question = { path: string; why: string; season?: number };
export type Fixes = {
  at: number | null;
  fixes: Partial<Record<FixKind, { count: number; sample: FixItem[] }>>;
  manual: Partial<Record<'shows' | 'seasons' | 'numbers' | 'films', { count: number; items: Question[] }>>;
  left: number;  // questions the reader left as is
};
export type FixResult = { done: Partial<Record<FixKind, number>>; failed: { path: string; why: string }[] };

export class ApiError extends Error {}

export type AuthMode = 'login' | 'setup';
export type AuthState = { required: boolean; set: boolean; signedIn: boolean };

// The app shows the sign-in page when this fires: the server said this browser isn't signed in (any more).
export const AUTH_EVENT = 'muthur-auth';
export const askToSignIn = (mode: AuthMode) => window.dispatchEvent(new CustomEvent<AuthMode>(AUTH_EVENT, { detail: mode }));

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...init });
  if (!r.ok) {
    let message = `The server answered with an error (${r.status}).`;
    try {
      const body = await r.json();
      if (typeof body.detail === 'string') message = body.detail;
      if (r.status === 401 && (body.auth === 'login' || body.auth === 'setup')) askToSignIn(body.auth);
    } catch {
      // keep the generic message
    }
    throw new ApiError(message);
  }
  return r.json() as Promise<T>;
}

export const api = {
  auth: () => call<AuthState>('/api/auth'),
  setup: (password: string) => call<{ signedIn: boolean }>('/api/auth/setup', { method: 'POST', body: JSON.stringify({ password }) }),
  login: (password: string) => call<{ signedIn: boolean }>('/api/auth/login', { method: 'POST', body: JSON.stringify({ password }) }),
  logout: () => call<{ signedIn: boolean }>('/api/auth/logout', { method: 'POST', body: '{}' }),
  changePassword: (current: string, next: string) =>
    call<{ signedIn: boolean }>('/api/auth/password', { method: 'POST', body: JSON.stringify({ current, new: next }) }),
  status: () => call<Status>('/api/status'),
  inbox: () => call<Inbox>('/api/inbox'),
  scan: () => call<Job>('/api/inbox/scan', { method: 'POST' }),
  learnShows: () => call<Job>('/api/memory/import', { method: 'POST' }),
  job: () => call<Job | null>('/api/jobs/current'),
  settings: () => call<Settings>('/api/settings'),
  saveSettings: (body: unknown) => call<Settings>('/api/settings', { method: 'PUT', body: JSON.stringify(body) }),
  testDownloadStation: () => call<{ connected: true; tasks: number } | { connected: false; problem: string }>('/api/downloadstation/test', { method: 'POST' }),
  shieldApps: () => call<{ apps: string[]; current: string | null }>('/api/shield/apps'),
  wakeShield: () => call<{ ok: boolean; woke: boolean; note?: string }>('/api/shield/wake', { method: 'POST' }),
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
  backupWatched: () => call<unknown>('/api/watched/backup', { method: 'POST' }),
  acceptWatched: () => call<unknown>('/api/watched/accept', { method: 'POST' }),
  restorePreview: () => call<{ count: number; check: string; watched: number; resume: number; sample: string[] }>('/api/watched/restore/preview', { method: 'POST' }),
  restore: (check: string) => call<{ done: number; failed: number }>('/api/watched/restore', { method: 'POST', body: JSON.stringify({ check }) }),
  library: () => call<Library>('/api/library'),
  libraryShow: (folder: string) => call<ShowDetail>(`/api/library/show?${new URLSearchParams({ folder })}`),
  libraryMatch: (kind: Kind, path: string, tmdbId: number) =>
    call<{ label: string }>('/api/library/match', { method: 'POST', body: JSON.stringify({ kind, path, tmdbId }) }),
  libraryTitle: (nfo: string, title: string) => call<{ label: string }>('/api/library/title', { method: 'POST', body: JSON.stringify({ nfo, title }) }),
  libraryPosters: (kind: Kind, tmdbId: number) =>
    call<{ posters: { path: string; language: string | null; votes: number }[] }>(`/api/library/posters?${new URLSearchParams({ kind, tmdbId: String(tmdbId) })}`),
  libraryPoster: (target: string, image: string) => call<{ label: string }>('/api/library/poster', { method: 'POST', body: JSON.stringify({ target, image }) }),
  indexLibrary: () => call<Job>('/api/library/scan', { method: 'POST' }),
  episodeReread: (path: string) => call<{ text: string }>('/api/library/episode/reread', { method: 'POST', body: JSON.stringify({ path }) }),
  episodeNfo: (path: string) => call<{ text: string }>('/api/library/episode/nfo', { method: 'POST', body: JSON.stringify({ path }) }),
  episodeRename: (path: string, as?: { season: number; episode: number }) =>
    call<Job>('/api/library/episode/rename', { method: 'POST', body: JSON.stringify({ path, ...(as ?? {}) }) }),
  duplicates: () => call<{ at: number | null; groups: DupGroup[] }>('/api/duplicates'),
  scanDuplicates: () => call<Job>('/api/duplicates/scan', { method: 'POST' }),
  duplicatePlan: (id: string, keep: string) => call<DupPlan>('/api/duplicates/plan', { method: 'POST', body: JSON.stringify({ id, keep }) }),
  applyDuplicates: (choices: { id: string; keep: string }[]) =>
    call<Job>('/api/duplicates/apply', { method: 'POST', body: JSON.stringify({ choices }) }),
  duplicatesLast: () => call<DupResult | Record<string, never>>('/api/duplicates/last'),
  fixes: (left = false) => call<Fixes>(`/api/fixes${left ? '?left=true' : ''}`),
  leaveQuestions: (body: { items?: Question[]; under?: string; back?: boolean }) =>
    call<{ changed: number }>('/api/fixes/leave', { method: 'POST', body: JSON.stringify(body) }),
  quarantineDownload: (id: string) => call<{ run: number }>('/api/inbox/quarantine', { method: 'POST', body: JSON.stringify({ id }) }),
  checkFixes: () => call<Job>('/api/fixes/check', { method: 'POST' }),
  applyFixes: (kinds: FixKind[]) => call<Job>('/api/fixes/apply', { method: 'POST', body: JSON.stringify({ kinds }) }),
  chooseForLibrary: (kind: Kind, path: string, tmdbId: number) =>
    call<{ fixes: Partial<Record<FixKind, number>>; questions: number }>('/api/fixes/choose', { method: 'POST', body: JSON.stringify({ kind, path, tmdbId }) }),
  fixesLast: () => call<FixResult | Record<string, never>>('/api/fixes/last'),
  quarantine: () => call<{ days: { day: string; files: number; size: number }[] }>('/api/quarantine'),
  quarantineDay: (day: string) => call<{ notes: { at: number; run: number; from: string; to: string; why: string }[] }>(`/api/quarantine/${day}`),
  emptyQuarantine: (days: string[]) =>
    call<{ emptied: string[]; freed: number }>('/api/quarantine/empty', { method: 'POST', body: JSON.stringify({ days, confirm: 'delete' }) }),
  refreshScores: () => call<Job>('/api/scores/refresh', { method: 'POST' }),
  forget: (id: string) => call<Item>('/api/review/forget', { method: 'POST', body: JSON.stringify({ id }) }),
};
