// Types and calls for muthur's JSON API (src/muthur/web.py).
export class ApiError extends Error {
}
// The app shows the sign-in page when this fires: the server said this browser isn't signed in (any more).
export const AUTH_EVENT = 'muthur-auth';
export const askToSignIn = (mode) => window.dispatchEvent(new CustomEvent(AUTH_EVENT, { detail: mode }));
async function call(path, init) {
    const r = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...init });
    if (!r.ok) {
        let message = `The server answered with an error (${r.status}).`;
        try {
            const body = await r.json();
            if (typeof body.detail === 'string')
                message = body.detail;
            if (r.status === 401 && (body.auth === 'login' || body.auth === 'setup'))
                askToSignIn(body.auth);
        }
        catch {
            // keep the generic message
        }
        throw new ApiError(message);
    }
    return r.json();
}
export const api = {
    auth: () => call('/api/auth'),
    setup: (password) => call('/api/auth/setup', { method: 'POST', body: JSON.stringify({ password }) }),
    login: (password) => call('/api/auth/login', { method: 'POST', body: JSON.stringify({ password }) }),
    logout: () => call('/api/auth/logout', { method: 'POST', body: '{}' }),
    changePassword: (current, next) => call('/api/auth/password', { method: 'POST', body: JSON.stringify({ current, new: next }) }),
    status: () => call('/api/status'),
    inbox: () => call('/api/inbox'),
    scan: () => call('/api/inbox/scan', { method: 'POST' }),
    learnShows: () => call('/api/memory/import', { method: 'POST' }),
    job: () => call('/api/jobs/current'),
    settings: () => call('/api/settings'),
    saveSettings: (body) => call('/api/settings', { method: 'PUT', body: JSON.stringify(body) }),
    testOpenSubtitles: () => call('/api/opensubtitles/test', { method: 'POST' }),
    subtitleSearch: (path) => call(`/api/library/subtitles?${new URLSearchParams({ path })}`),
    subtitleSave: (path, fileId, language) => call('/api/library/subtitles', { method: 'POST', body: JSON.stringify({ path, fileId, language }) }),
    testDownloadStation: () => call('/api/downloadstation/test', { method: 'POST' }),
    shieldApps: () => call('/api/shield/apps'),
    wakeShield: () => call('/api/shield/wake', { method: 'POST' }),
    testKodi: () => call('/api/kodi/test', { method: 'POST' }),
    scanKodi: () => call('/api/kodi/scan', { method: 'POST' }),
    apply: (ids) => call('/api/apply', { method: 'POST', body: JSON.stringify(ids ? { ids } : {}) }),
    history: () => call('/api/history'),
    run: (id) => call(`/api/history/${id}`),
    undo: (id) => call(`/api/history/${id}/undo`, { method: 'POST', body: '{}' }),
    search: (kind, q, year) => call(`/api/tmdb/search?${new URLSearchParams({ kind, q, ...(year ? { year: String(year) } : {}) })}`),
    resolve: (link) => call('/api/tmdb/resolve', { method: 'POST', body: JSON.stringify({ link }) }),
    season: (tvId, season) => call(`/api/tmdb/tv/${tvId}/season/${season}`),
    preview: (id, choice) => call('/api/review/preview', { method: 'POST', body: JSON.stringify({ id, choice }) }),
    choose: (id, choice, remember) => call('/api/review/choose', { method: 'POST', body: JSON.stringify({ id, choice, remember }) }),
    backupWatched: () => call('/api/watched/backup', { method: 'POST' }),
    acceptWatched: () => call('/api/watched/accept', { method: 'POST' }),
    restorePreview: () => call('/api/watched/restore/preview', { method: 'POST' }),
    restore: (check) => call('/api/watched/restore', { method: 'POST', body: JSON.stringify({ check }) }),
    library: () => call('/api/library'),
    libraryShow: (folder) => call(`/api/library/show?${new URLSearchParams({ folder })}`),
    libraryMatch: (kind, path, tmdbId) => call('/api/library/match', { method: 'POST', body: JSON.stringify({ kind, path, tmdbId }) }),
    libraryTitle: (nfo, title) => call('/api/library/title', { method: 'POST', body: JSON.stringify({ nfo, title }) }),
    libraryPosters: (kind, tmdbId) => call(`/api/library/posters?${new URLSearchParams({ kind, tmdbId: String(tmdbId) })}`),
    libraryPoster: (target, image) => call('/api/library/poster', { method: 'POST', body: JSON.stringify({ target, image }) }),
    indexLibrary: () => call('/api/library/scan', { method: 'POST' }),
    episodeReread: (path) => call('/api/library/episode/reread', { method: 'POST', body: JSON.stringify({ path }) }),
    episodeNfo: (path) => call('/api/library/episode/nfo', { method: 'POST', body: JSON.stringify({ path }) }),
    episodeRename: (path, as) => call('/api/library/episode/rename', { method: 'POST', body: JSON.stringify({ path, ...(as ?? {}) }) }),
    duplicates: () => call('/api/duplicates'),
    scanDuplicates: () => call('/api/duplicates/scan', { method: 'POST' }),
    duplicatePlan: (id, keep) => call('/api/duplicates/plan', { method: 'POST', body: JSON.stringify({ id, keep }) }),
    applyDuplicates: (choices) => call('/api/duplicates/apply', { method: 'POST', body: JSON.stringify({ choices }) }),
    duplicatesLast: () => call('/api/duplicates/last'),
    fixes: (left = false) => call(`/api/fixes${left ? '?left=true' : ''}`),
    leaveQuestions: (body) => call('/api/fixes/leave', { method: 'POST', body: JSON.stringify(body) }),
    quarantineDownload: (id) => call('/api/inbox/quarantine', { method: 'POST', body: JSON.stringify({ id }) }),
    checkFixes: () => call('/api/fixes/check', { method: 'POST' }),
    libraryOrders: (folder) => call(`/api/library/orders?${new URLSearchParams({ folder })}`),
    setOrder: (folder, groupId) => call('/api/library/order', { method: 'POST', body: JSON.stringify({ folder, groupId }) }),
    trustNumber: (path) => call('/api/fixes/trust', { method: 'POST', body: JSON.stringify({ path }) }),
    applyFixes: (kinds) => call('/api/fixes/apply', { method: 'POST', body: JSON.stringify({ kinds }) }),
    chooseForLibrary: (kind, path, tmdbId) => call('/api/fixes/choose', { method: 'POST', body: JSON.stringify({ kind, path, tmdbId }) }),
    fixesLast: () => call('/api/fixes/last'),
    quarantine: () => call('/api/quarantine'),
    quarantineDay: (day) => call(`/api/quarantine/${day}`),
    emptyQuarantine: (days) => call('/api/quarantine/empty', { method: 'POST', body: JSON.stringify({ days, confirm: 'delete' }) }),
    refreshScores: () => call('/api/scores/refresh', { method: 'POST' }),
    forget: (id) => call('/api/review/forget', { method: 'POST', body: JSON.stringify({ id }) }),
    // The player (docs/PLAYER.md)
    playerItems: () => call('/api/player/items'),
    playerShow: (folder) => call(`/api/player/show?${new URLSearchParams({ folder })}`),
    playerTestSet: () => call('/api/player/testset'),
    playerInfo: (id) => call(`/api/player/video/${id}/info`),
    playerScan: () => call('/api/player/scan', { method: 'POST' }),
    playerExtract: (id) => call(`/api/player/video/${id}/subtitles/extract`, { method: 'POST' }),
    playerLinks: (id) => call(`/api/player/video/${id}/links`),
    playerTv: (id) => call(`/api/player/video/${id}/tv`, { method: 'POST', body: '{}' }),
};
