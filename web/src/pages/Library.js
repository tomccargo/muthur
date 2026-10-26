import { Fragment as _Fragment, jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import { Dot, JobError, Loading } from '../components';
import { count, hue, middle, score, size, when } from '../labels';
import { Link, navigate, useLocation } from '../nav';
import { LibraryEditor } from './LibraryEdit';
import { SubtitleSearch } from './Subtitles';
import { hero, heroClick, heroLanded, motionOn } from '../motion';
// The page a poster was clicked for: its cover takes over the flying poster (motion.ts).
const isFlying = () => motionOn() && hero.to === location.pathname + location.search;
// A film's own folder: where its video is, which may be a folder deeper than the film's top folder.
const filmDir = (f) => (f.file && f.file.includes('/') ? f.file.split('/').slice(0, -1).join('/') : f.key);
// Each problem filter says where it's fixed.
const FIX_HINT = {
    noNfo: ['Health writes the missing NFOs.', '/health', 'Open Health'],
    noScore: ['Health adds IMDb scores, and downloads them for shows that have none yet.', '/health', 'Open Health'],
    duplicates: ['Choose which copy to keep in Duplicates.', '/duplicates', 'Open Duplicates'],
    damaged: ['Health lists these under Needs you, to say which episode each one is.', '/health', 'Open Health'],
};
const FILTERS = [['all', 'All'], ['noNfo', 'Missing NFO'], ['noScore', 'No IMDb score'], ['duplicates', 'Duplicates'], ['damaged', 'Damaged names']];
export const art = (path) => `/api/library/art?${new URLSearchParams({ path })}`;
const code = (s, e) => (s == null ? '—' : `S${String(s).padStart(2, '0')}${e.map((n) => `E${String(n).padStart(2, '0')}`).join('')}`);
// A poster from the library, or the title's initials when there is none (DESIGN.md §8).
export function Cover({ src, title, width = '100%', hero = false }) {
    const [failed, setFailed] = useState(false);
    const style = { width, ...(hero ? { viewTransitionName: 'hero' } : {}) };
    if (!src || failed) {
        const initials = title.split(/\s+/).filter((w) => /\w/.test(w)).slice(0, 2).map((w) => w[0]).join('').toUpperCase();
        return _jsx("span", { className: "poster", style: { ...style, '--hue': hue(title) }, "aria-hidden": "true", children: _jsx("span", { className: "poster-initials", children: initials || '?' }) });
    }
    return _jsx("img", { className: "poster", style: style, src: src, alt: "", loading: hero ? 'eager' : 'lazy', onError: () => setFailed(true) });
}
function Links({ ids, kind }) {
    const out = [];
    if (ids.imdb)
        out.push(['IMDb', `https://www.imdb.com/title/${ids.imdb}/`]);
    if (ids.tmdb)
        out.push(['TMDB', `https://www.themoviedb.org/${kind}/${ids.tmdb}`]);
    if (ids.tvdb && kind === 'tv')
        out.push(['TVDB', `https://thetvdb.com/dereferrer/series/${ids.tvdb}`]);
    if (!out.length)
        return _jsx("span", { className: "small muted", children: "No IDs in the NFO" });
    return _jsx("span", { className: "small", children: out.map(([label, href], i) => _jsxs("span", { children: [i > 0 && ' · ', _jsx("a", { href: href, target: "_blank", rel: "noreferrer", children: label })] }, label)) });
}
function problemsText(p, film = false) {
    const out = [];
    if (p.noNfo)
        out.push(film ? 'No NFO' : `${p.noNfo} without an NFO`);
    if (p.damaged)
        out.push(film ? 'Video missing or too small' : `${p.damaged} with a damaged or missing number`);
    if (p.duplicates)
        out.push(film ? `${p.duplicates + 1} copies` : `${count(p.duplicates, 'number')} twice`);
    if (p.loose)
        out.push(`${p.loose} leftover files`);
    return out;
}
// ---- a show -------------------------------------------------------------------------------
// One episode's actions, opened from its row: Kodi re-reads it, an NFO where it has none, the library's name,
// or the number it really has. The result shows here (DESIGN.md §7.5); a rename runs as a job.
function EpisodeMenu({ e, path, tmdbId, onClose }) {
    const [busy, setBusy] = useState(null);
    const [result, setResult] = useState(null);
    const [other, setOther] = useState(null);
    const [season, setSeason] = useState(e.season ?? 1);
    const [episode, setEpisode] = useState(null);
    const [subs, setSubs] = useState(false);
    const run = (key, request) => {
        setBusy(key);
        setResult(null);
        request().then((r) => setResult({ kind: 'note', text: r.text })).catch((err) => setResult({ kind: 'error', text: err.message })).finally(() => setBusy(null));
    };
    const renamed = (as) => run(as ? 'other' : 'rename', () => api.episodeRename(path, as).then(() => ({ text: 'Renaming: the bar at the top shows it; this page updates when it’s done.' })));
    const loadSeason = (s) => {
        if (!tmdbId)
            return;
        setSeason(s);
        setEpisode(null);
        api.season(tmdbId, s).then(setOther).catch((err) => setResult({ kind: 'error', text: err.message }));
    };
    const picked = other?.episodes.find((x) => x.episode === episode);
    return (_jsxs("div", { style: { gridColumn: '1 / -1', display: 'flex', flexDirection: 'column', gap: 8, padding: '8px 0 4px' }, children: [_jsxs("div", { className: "actions", style: { flexWrap: 'wrap' }, children: [_jsx("button", { type: "button", className: "btn btn-secondary btn-sm", "aria-busy": busy === 'kodi', onClick: () => run('kodi', () => api.episodeReread(path)), children: "Re-read in Kodi" }), !e.nfo && _jsx("button", { type: "button", className: "btn btn-secondary btn-sm", "aria-busy": busy === 'nfo', onClick: () => run('nfo', () => api.episodeNfo(path)), children: "Write its NFO" }), e.renameTo && (_jsxs("button", { type: "button", className: "btn btn-secondary btn-sm", "aria-busy": busy === 'rename', title: e.renameTo, onClick: () => renamed(), children: ["Rename to \u201C", middle(e.renameTo, 60), "\u201D"] })), !subs && _jsx("button", { type: "button", className: "btn btn-secondary btn-sm", onClick: () => setSubs(true), children: "Find subtitles" }), tmdbId && !other && _jsx("button", { type: "button", className: "btn btn-ghost btn-sm", onClick: () => loadSeason(e.season ?? 1), children: "It\u2019s another episode" }), _jsx("button", { type: "button", className: "btn btn-ghost btn-sm", onClick: onClose, children: "Close" })] }), subs && _jsx(SubtitleSearch, { path: path }), other && (_jsxs("div", { className: "actions", style: { flexWrap: 'wrap' }, children: [_jsx("select", { className: "field", "aria-label": "Season", value: season, onChange: (ev) => loadSeason(Number(ev.target.value)), style: { width: 'auto' }, children: other.seasons.map((s) => _jsx("option", { value: s.season, children: s.season === 0 ? 'Specials' : `Season ${s.season}` }, s.season)) }), _jsxs("select", { className: "field", "aria-label": "Episode", value: episode ?? '', onChange: (ev) => setEpisode(Number(ev.target.value) || null), style: { width: 'auto', minWidth: 0, maxWidth: '100%' }, children: [_jsx("option", { value: "", children: "Which episode?" }), other.episodes.map((x) => _jsxs("option", { value: x.episode, children: [`E${String(x.episode).padStart(2, '0')}`, " \u00B7 ", x.title ?? '—'] }, x.episode))] }), picked && (_jsxs("button", { type: "button", className: "btn btn-secondary btn-sm", "aria-busy": busy === 'other', onClick: () => renamed({ season, episode: picked.episode }), children: ["It\u2019s ", code(season, [picked.episode]), " \u201C", picked.title, "\u201D"] }))] })), other && _jsx("p", { className: "hint", style: { margin: 0 }, children: "The file gets that number and title, and its NFO describes that episode. Kodi keeps the watched status." }), result && _jsx("div", { className: `banner banner-${result.kind}`, role: result.kind === 'error' ? 'alert' : 'status', children: result.text })] }));
}
function EpisodeRow({ e, path, tmdbId }) {
    const [open, setOpen] = useState(false);
    const name = e.file.split('/').pop() ?? e.file;
    const flags = [!e.nfo && 'no NFO', e.damaged && 'damaged number', e.season == null && !e.damaged && 'no number', e.duplicate && 'number twice', e.mismatch && 'NFO says another number']
        .filter(Boolean);
    return (_jsxs("li", { className: "ep-row", children: [_jsx("span", { className: "mono small", children: code(e.season, e.episodes) }), _jsxs("span", { className: "ep-main", children: [_jsx("span", { className: "ellipsis", style: { display: 'block' }, children: e.title ?? _jsx("span", { className: "muted", children: "\u2014" }) }), _jsx("span", { className: "mono small muted ellipsis", style: { display: 'block' }, title: e.file, children: middle(name, 70) }), flags.length > 0 && _jsx("span", { className: "small", style: { color: 'var(--warn-text)' }, children: flags.join(' · ') }), (e.subLangs?.length ?? 0) > 0 && _jsxs("span", { className: "small muted", style: { display: 'block' }, children: ["Subtitles ", e.subLangs.join(' · ')] })] }), _jsxs("span", { className: "ep-meta", children: [_jsx("span", { className: "small num", children: score(e.rating) || _jsx("span", { className: "muted", children: "no score" }) }), _jsx("span", { className: "status small", children: e.watched ? _jsxs(_Fragment, { children: [_jsx(Dot, { kind: "dot-success" }), "Watched"] }) : e.watched === 0 ? _jsxs(_Fragment, { children: [_jsx(Dot, {}), "Not watched"] }) : _jsx("span", { className: "muted", children: "\u2014" }) })] }), _jsx("button", { type: "button", className: "btn btn-ghost btn-sm ep-menu", "aria-expanded": open, "aria-label": `Actions for ${code(e.season, e.episodes)}`, title: "Re-read, NFO, rename", onClick: () => setOpen(!open), children: "\u22EF" }), open && _jsx(EpisodeMenu, { e: e, path: path, tmdbId: tmdbId, onClose: () => setOpen(false) })] }));
}
function ShowPage({ folder, finished }) {
    const [show, setShow] = useState(null);
    const [error, setError] = useState(null);
    const [note, setNote] = useState(null);
    const [flying] = useState(isFlying);
    // Again after every job (a rename, the index built again): the page shows the library as it is now.
    useEffect(() => { api.libraryShow(folder).then(setShow).catch((e) => { setError(e.message); heroLanded(); }); }, [folder, finished]);
    useEffect(() => { if (show && flying)
        heroLanded(); }, [show, flying]);
    const seasons = useMemo(() => {
        const m = new Map();
        for (const e of show?.episodes ?? [])
            m.set(e.season, [...(m.get(e.season) ?? []), e]);
        const byNumber = (a, b) => (a.episodes[0] ?? 9999) - (b.episodes[0] ?? 9999) || a.file.localeCompare(b.file);
        return [...m.entries()].sort((a, b) => (a[0] ?? 999) - (b[0] ?? 999)).map(([s, eps]) => [s, [...eps].sort(byNumber)]);
    }, [show]);
    const [season, setSeason] = useState(undefined);
    const shown = seasons.find(([s]) => s === season) ?? seasons[0];
    return (_jsxs("div", { className: "page", children: [_jsx(Link, { to: "/library", className: "btn btn-ghost btn-sm", style: { alignSelf: 'flex-start' }, children: "\u2190 Library" }), error && _jsx("div", { className: "banner banner-error", role: "alert", children: error }), !show && !error && _jsx(Loading, { rows: 4, label: "Loading the show" }), show && (_jsxs(_Fragment, { children: [_jsxs("header", { style: { display: 'grid', gridTemplateColumns: 'minmax(0, 120px) minmax(0, 1fr)', gap: 20, alignItems: 'start' }, children: [_jsx(Cover, { src: show.poster ? art(`TV/${show.folder}/poster.jpg`) : null, title: show.title, hero: flying }), _jsxs("div", { style: { display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 }, children: [_jsx("p", { className: "eyebrow", children: "Show" }), _jsxs("h1", { style: { margin: 0, fontSize: '2rem', overflowWrap: 'anywhere' }, children: [show.title, show.year ? ` (${show.year})` : ''] }), _jsxs("span", { className: "mono small muted", children: ["TV/", show.folder, "/"] }), _jsx(Links, { ids: show.ids, kind: "tv" }), _jsxs("span", { className: "small", children: [count(show.count, 'episode'), " \u00B7 ", count(show.seasons, 'season'), " \u00B7 ", size(show.size), " \u00B7 ", show.watched, " watched", show.rating ? ` · ${score(show.rating)}` : ''] }), problemsText(show.problems).length > 0 && _jsx("span", { className: "small", style: { color: 'var(--warn-text)' }, children: problemsText(show.problems).join(' · ') }), !show.nfo && _jsx("span", { className: "small", style: { color: 'var(--warn-text)' }, children: "The show folder has no tvshow.nfo." })] })] }), note && _jsx("div", { className: "banner banner-note", role: "status", children: note }), _jsx(LibraryEditor, { kind: "tv", path: `TV/${show.folder}`, nfo: show.nfo ? `TV/${show.folder}/tvshow.nfo` : null, posterTarget: `TV/${show.folder}/poster.jpg`, tmdbId: show.ids.tmdb ? Number(show.ids.tmdb) : null, title: show.title, onDone: (text) => { setNote(text); api.libraryShow(folder).then(setShow).catch(() => undefined); } }), seasons.length > 1 && (_jsx("div", { className: "seg filters", role: "group", "aria-label": "Seasons", children: seasons.map(([s, eps]) => (_jsxs("button", { type: "button", "aria-pressed": shown?.[0] === s, onClick: () => setSeason(s), children: [s == null ? 'No number' : s === 0 ? 'Specials' : `Season ${s}`, eps.some((e) => !e.nfo || !e.imdb || e.damaged || e.duplicate) && _jsx(Dot, { kind: "dot-warning" })] }, String(s)))) })), shown && (() => {
                        const [s, eps] = shown;
                        const why = s != null ? show.scoreNotes?.[String(s)] : undefined;
                        return (_jsxs("section", { className: "panel", "aria-label": s == null ? 'Without a number' : `Season ${s}`, children: [_jsxs("div", { className: "panel-head", children: [_jsx("h2", { children: s == null ? 'Without a season number' : s === 0 ? 'Specials' : `Season ${s}` }), _jsxs("span", { className: "small muted", children: [count(eps.length, 'episode'), " \u00B7 ", eps.filter((e) => e.watched).length, " watched"] })] }), why && (_jsxs("p", { className: "hint", style: { margin: '0 0 8px', color: 'var(--warn-text)' }, children: [why, why.includes('Health') && _jsxs(_Fragment, { children: [" ", _jsx(Link, { to: "/health", children: "Open Health" })] })] })), _jsx("ul", { className: "rows", children: eps.map((e) => _jsx(EpisodeRow, { e: e, path: `TV/${show.folder}/${e.file}`, tmdbId: show.ids.tmdb ? Number(show.ids.tmdb) : null }, e.file)) })] }));
                    })(), show.loose.length > 0 && (_jsxs("section", { className: "panel", "aria-labelledby": "loose-h", children: [_jsxs("div", { className: "panel-head", children: [_jsx("h2", { id: "loose-h", children: "Leftover files" }), _jsx("span", { className: "small muted", children: "belong to no video" })] }), _jsx("ul", { className: "rows", children: show.loose.map((f) => _jsx("li", { children: _jsx("span", { className: "mono small", style: { wordBreak: 'break-all' }, children: f }) }, f)) })] }))] }))] }));
}
// ---- a film -------------------------------------------------------------------------------
function FilmPage({ film }) {
    const [note, setNote] = useState(null);
    const [findSubs, setFindSubs] = useState(false);
    const [flying] = useState(isFlying);
    useEffect(() => { if (flying)
        heroLanded(); }, [flying]);
    const stem = film.file ? `Film/${film.file.replace(/\.[^.]+$/, '')}` : '';
    return (_jsxs("div", { className: "page", children: [_jsx(Link, { to: "/library?kind=film", className: "btn btn-ghost btn-sm", style: { alignSelf: 'flex-start' }, children: "\u2190 Library" }), _jsxs("header", { style: { display: 'grid', gridTemplateColumns: 'minmax(0, 120px) minmax(0, 1fr)', gap: 20, alignItems: 'start' }, children: [_jsx(Cover, { src: film.poster ? art(`Film/${filmDir(film)}/poster.jpg`) : null, title: film.title, hero: flying }), _jsxs("div", { style: { display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 }, children: [_jsx("p", { className: "eyebrow", children: "Film" }), _jsxs("h1", { style: { margin: 0, fontSize: '2rem', overflowWrap: 'anywhere' }, children: [film.title, film.year ? ` (${film.year})` : ''] }), _jsx(Links, { ids: film.ids, kind: "movie" }), _jsxs("span", { className: "small", children: [score(film.rating) || 'No score in the NFO', " \u00B7 ", film.watched ? 'watched' : film.watched === 0 ? 'not watched' : 'not in the watched backup'] }), problemsText(film.problems, true).length > 0 && _jsx("span", { className: "small", style: { color: 'var(--warn-text)' }, children: problemsText(film.problems, true).join(' · ') })] })] }), note && _jsx("div", { className: "banner banner-note", role: "status", children: note }), film.file && (_jsx(LibraryEditor, { kind: "movie", path: `Film/${film.file}`, nfo: film.nfoFile ? `Film/${film.nfoFile}` : null, posterTarget: film.folder ? `Film/${film.key}/poster.jpg` : `${stem}-poster.jpg`, tmdbId: film.ids.tmdb ? Number(film.ids.tmdb) : null, title: film.title, onDone: setNote })), _jsxs("section", { className: "panel", "aria-labelledby": "files-h", children: [_jsx("div", { className: "panel-head", children: _jsx("h2", { id: "files-h", children: "Files" }) }), _jsxs("ul", { className: "rows", children: [film.file && _jsxs("li", { children: [_jsxs("span", { className: "mono small", style: { wordBreak: 'break-all' }, children: ["Film/", film.file] }), _jsx("span", { className: "small num", children: size(film.size) })] }), film.others.map((o) => _jsxs("li", { children: [_jsxs("span", { className: "mono small muted", style: { wordBreak: 'break-all' }, children: ["Film/", o] }), _jsx("span", { className: "small muted", children: "extra or second copy" })] }, o)), !film.file && _jsx("li", { children: _jsx("span", { className: "small", style: { color: 'var(--warn-text)' }, children: "No video in this folder." }) })] })] }), film.file && (_jsxs("section", { className: "panel", "aria-labelledby": "subs-h", style: { display: 'flex', flexDirection: 'column', gap: 8 }, children: [_jsxs("div", { className: "panel-head", style: { marginBottom: 0 }, children: [_jsx("h2", { id: "subs-h", children: "Subtitles" }), !findSubs && _jsx("button", { type: "button", className: "btn btn-secondary btn-sm", onClick: () => setFindSubs(true), children: "Find subtitles" })] }), findSubs && _jsx(SubtitleSearch, { path: `Film/${film.file}` })] }))] }));
}
// ---- the grid -----------------------------------------------------------------------------
export function LibraryPage({ status, refresh }) {
    const { search } = useLocation();
    const params = new URLSearchParams(search);
    const kind = params.get('kind') === 'film' ? 'film' : 'tv';
    const filter = (params.get('show') ?? 'all');
    const folder = params.get('folder');
    const filmKey = params.get('film');
    const [lib, setLib] = useState(null);
    const [query, setQuery] = useState('');
    const [error, setError] = useState(null);
    const running = Boolean(status?.job?.running);
    useEffect(() => { api.library().then(setLib).catch((e) => setError(e.message)); }, [running, status?.job?.finished]);
    const go = (k, f) => navigate(`/library?${new URLSearchParams({ ...(k === 'film' ? { kind: 'film' } : {}), ...(f !== 'all' ? { show: f } : {}) })}`.replace(/\?$/, ''));
    const matches = (title, p) => (filter === 'all' || p[filter] > 0) && title.toLowerCase().includes(query.trim().toLowerCase());
    const shows = useMemo(() => (lib?.shows ?? []).filter((s) => matches(s.title, s.problems)), [lib, filter, query]); // eslint-disable-line react-hooks/exhaustive-deps
    const films = useMemo(() => (lib?.films ?? []).filter((f) => matches(f.title, f.problems)), [lib, filter, query]); // eslint-disable-line react-hooks/exhaustive-deps
    const inFilter = (f) => (kind === 'tv' ? lib?.shows ?? [] : lib?.films ?? []).filter((x) => f === 'all' || x.problems[f] > 0).length;
    // The button pressed spins until its request is answered; a job then shows in the job bar (DESIGN.md §7.6).
    // Every hook comes before the returns below: the list and a show are one component, and React counts its hooks.
    const [starting, setStarting] = useState(null);
    if (folder)
        return _jsx(ShowPage, { folder: folder, finished: status?.job?.finished });
    const film = filmKey ? lib?.films.find((f) => f.key === filmKey) : null;
    if (film)
        return _jsx(FilmPage, { film: film });
    const begin = (key, request) => {
        setStarting(key);
        setError(null);
        request().then(refresh).catch((e) => setError(e.message)).finally(() => setStarting(null));
    };
    const index = () => begin('index', api.indexLibrary);
    const episodes = (lib?.shows ?? []).reduce((n, s) => n + s.count, 0);
    return (_jsxs("div", { className: "page", children: [_jsxs("header", { className: "page-head", children: [_jsxs("div", { children: [_jsx("p", { className: "eyebrow", children: "Library" }), _jsx("h1", { children: "Shows and films" }), _jsx("p", { className: "lede", children: lib?.at ? `${count(lib.shows.length, 'show')} · ${count(episodes, 'episode')} · ${count(lib.films.length, 'film')} · indexed ${when(lib.at)}` : 'Not indexed yet.' }), _jsxs("p", { className: "small muted", style: { margin: '4px 0 0' }, children: [count(status?.memory.shows ?? 0, 'show'), " muthur files new episodes into directly \u00B7 the rest it searches on TMDB"] })] }), _jsxs("div", { className: "actions", children: [_jsx("button", { className: "btn btn-secondary btn-sm", type: "button", "aria-busy": starting === 'learn', ...(status?.tmdb.configured ? {} : { 'aria-disabled': true }), title: status?.tmdb.configured ? 'Matches every show folder on TMDB and remembers the ones that agree with their tvshow.nfo. Changes no files. Useful after you add or rename show folders yourself.' : 'Add the TMDB token in Settings first', onClick: status?.tmdb.configured ? () => begin('learn', api.learnShows) : undefined, children: "Read the TV folder" }), _jsx("button", { className: lib?.at ? 'btn btn-secondary btn-sm' : 'btn btn-primary', type: "button", "aria-busy": starting === 'index', onClick: index, children: lib?.at ? 'Index again' : 'Index the library' })] })] }), _jsx(JobError, { job: status?.job }), !lib && !error && _jsx(Loading, { label: "Loading the library" }), error && _jsx("div", { className: "banner banner-error", role: "alert", children: error }), _jsxs("div", { className: "inline", children: [_jsxs("div", { className: "seg", role: "group", "aria-label": "Library", children: [_jsx("button", { type: "button", "aria-pressed": kind === 'tv', onClick: () => go('tv', filter), children: "TV" }), _jsx("button", { type: "button", "aria-pressed": kind === 'film', onClick: () => go('film', filter), children: "Film" })] }), _jsx("input", { className: "field", type: "search", "aria-label": "Find a title", placeholder: "Find a title", value: query, onChange: (e) => setQuery(e.target.value) })] }), _jsx("div", { className: "seg filters", role: "group", "aria-label": "Show", children: FILTERS.map(([k, label]) => (_jsxs("button", { type: "button", "aria-pressed": filter === k, onClick: () => go(kind, k), children: [kind === 'film' && k === 'damaged' ? 'Video missing or too small' : label, " ", _jsx("span", { className: "num muted", children: inFilter(k) })] }, k))) }), FIX_HINT[filter] && (_jsxs("div", { className: "banner banner-note", children: [_jsx("span", { children: FIX_HINT[filter][0] }), _jsx(Link, { to: FIX_HINT[filter][1], children: FIX_HINT[filter][2] })] })), lib?.at && (kind === 'tv' ? shows : films).length === 0 && _jsx("p", { className: "hint", children: "Nothing here with this filter." }), _jsx("div", { className: "posters", children: kind === 'tv' ? shows.map((s) => (_jsxs(Link, { className: "poster-tile", to: `/library?${new URLSearchParams({ folder: s.folder })}`, title: s.title, onClick: (e) => heroClick(e, `/library?${new URLSearchParams({ folder: s.folder })}`), children: [_jsx(Cover, { src: s.poster ? art(`TV/${s.folder}/poster.jpg`) : null, title: s.title }), _jsx("span", { className: "poster-title", children: s.title }), _jsxs("span", { className: "small muted", children: [s.year ?? '', s.year ? ' · ' : '', s.count, " ep \u00B7 ", s.watched, " watched"] })] }, s.folder))) : films.map((f) => (_jsxs(Link, { className: "poster-tile", to: `/library?${new URLSearchParams({ kind: 'film', film: f.key })}`, title: f.title, onClick: (e) => heroClick(e, `/library?${new URLSearchParams({ kind: 'film', film: f.key })}`), children: [_jsx(Cover, { src: f.poster ? art(`Film/${filmDir(f)}/poster.jpg`) : null, title: f.title }), _jsx("span", { className: "poster-title", children: f.title }), _jsxs("span", { className: "small muted", children: [f.year ?? '—', f.imdb ? ` · IMDb ${f.imdb[0].toFixed(1)}` : '', f.watched ? ' · watched' : ''] })] }, f.key))) })] }));
}
