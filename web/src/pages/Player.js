import { Fragment as _Fragment, jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
// The player (docs/PLAYER.md): its own page at /player, outside muthur's sections. TV and Films as a visual grid with
// filters; a show's seasons and episodes; and the watch view, which fits the tab and goes full screen. Read-only:
// the files are played as they are, and nothing about watching is written anywhere.
import { useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../api';
import { Loading } from '../components';
import { hue } from '../labels';
import { Link, navigate, useLocation } from '../nav';
import { art } from './Library';
import { SubtitleSearch } from './Subtitles';
import './player.css';
const SORTS = [['added', 'Recently added'], ['title', 'Title'], ['year', 'Year'], ['rating', 'Rating']];
// H.264 in 10-bit plays in Chrome and Edge but not in Firefox (measured 26 Oct, docs/PLAYER.md §3): decided here, by the browser.
const HI10 = !/firefox/i.test(navigator.userAgent);
const way = (p) => (p.endsWith('-hi10') ? (HI10 ? p.slice(0, -5) : 'kodi') : p);
const MSE = typeof window !== 'undefined' && 'MediaSource' in window; // repacking in the browser (repack.ts) needs it
const PLAY_NOTE = {
    native: null,
    sound: MSE ? null : 'This browser can’t decode this file’s sound (AC3, E-AC3 or DTS): it plays without sound.',
    kodi: 'Plays in Kodi only: no browser plays this kind of file. The ⋯ menu above plays it on the TV, opens it in your own player, or downloads it.',
    unknown: null,
};
const code = (s, e) => (s == null ? '' : `S${String(s).padStart(2, '0')}${e.map((n) => `E${String(n).padStart(2, '0')}`).join('')}`);
const watchUrl = (id, title) => `/player/watch?${new URLSearchParams({ id, t: title })}`;
// A poster or thumbnail from the library, or the title's initials on a coloured card when there is none.
function Art({ path, title, wide = false }) {
    const [failed, setFailed] = useState(false);
    if (!path || failed) {
        const initials = title.split(/\s+/).filter((w) => /\w/.test(w)).slice(0, 2).map((w) => w[0]).join('').toUpperCase();
        return _jsx("span", { className: `pl-art pl-art-empty${wide ? ' wide' : ''}`, style: { '--hue': hue(title) }, "aria-hidden": "true", children: initials || '?' });
    }
    return _jsx("img", { className: `pl-art${wide ? ' wide' : ''}`, src: art(path), alt: "", loading: "lazy", onError: () => setFailed(true) });
}
function PlayMark() {
    return _jsx("span", { className: "pl-play", "aria-hidden": "true", children: _jsx("svg", { viewBox: "0 0 24 24", width: "28", height: "28", children: _jsx("path", { d: "M8 5v14l11-7z", fill: "currentColor" }) }) });
}
// ---- browsing -------------------------------------------------------------------------------
function useFilters(genres) {
    const [text, setText] = useState('');
    const [genre, setGenre] = useState('');
    const [seen, setSeen] = useState('all');
    const [decade, setDecade] = useState('');
    const [minRating, setMinRating] = useState(0);
    const [sort, setSort] = useState('added');
    const keep = (x, watched, partly = false) => (!text || x.title.toLowerCase().includes(text.toLowerCase()))
        && (!genre || x.genres.includes(genre))
        && (seen === 'all' || (seen === 'watched' ? watched : !watched || partly))
        && (!decade || (x.year != null && String(Math.floor(x.year / 10) * 10) === decade))
        && (!minRating || (x.rating ?? 0) >= minRating);
    const order = (list) => [...list].sort((a, b) => sort === 'title' ? a.title.localeCompare(b.title) : sort === 'year' ? (b.year ?? 0) - (a.year ?? 0)
        : sort === 'rating' ? (b.rating ?? 0) - (a.rating ?? 0) : b.added - a.added);
    const bar = (_jsxs("div", { className: "pl-filters", role: "search", children: [_jsx("input", { type: "search", placeholder: "Search titles", value: text, onChange: (e) => setText(e.target.value), "aria-label": "Search titles" }), _jsxs("select", { value: genre, onChange: (e) => setGenre(e.target.value), "aria-label": "Genre", children: [_jsx("option", { value: "", children: "All genres" }), genres.map((g) => _jsx("option", { value: g, children: g }, g))] }), _jsxs("select", { value: decade, onChange: (e) => setDecade(e.target.value), "aria-label": "Decade", children: [_jsx("option", { value: "", children: "Any year" }), ['2020', '2010', '2000', '1990', '1980', '1970', '1960', '1950'].map((d) => _jsxs("option", { value: d, children: [d, "s"] }, d))] }), _jsxs("select", { value: minRating, onChange: (e) => setMinRating(Number(e.target.value)), "aria-label": "Rating", children: [_jsx("option", { value: 0, children: "Any rating" }), [6, 7, 8].map((r) => _jsxs("option", { value: r, children: [r, "+"] }, r))] }), _jsx("span", { className: "pl-seg", role: "group", "aria-label": "Watched", children: ['all', 'unwatched', 'watched'].map((s) => (_jsx("button", { type: "button", "aria-pressed": seen === s, onClick: () => setSeen(s), children: s === 'all' ? 'All' : s === 'watched' ? 'Watched' : 'Unwatched' }, s))) }), _jsx("select", { value: sort, onChange: (e) => setSort(e.target.value), "aria-label": "Sort", children: SORTS.map(([k, l]) => _jsx("option", { value: k, children: l }, k)) })] }));
    return { keep, order, bar };
}
function FilmTile({ f }) {
    const kodi = way(f.play) === 'kodi';
    const label = `${f.title}${f.year ? ` (${f.year})` : ''}`;
    const body = (_jsxs(_Fragment, { children: [_jsxs("span", { className: "pl-cover", children: [_jsx(Art, { path: f.poster, title: f.title }), !kodi && _jsx(PlayMark, {}), kodi && _jsx("span", { className: "pl-badge", children: "Kodi only" }), f.watched && _jsx("span", { className: "pl-tick", title: "Watched", "aria-label": "Watched", children: "\u2713" })] }), _jsx("span", { className: "pl-name", children: f.title }), _jsx("span", { className: "pl-sub", children: [f.year, f.rating ? `★ ${f.rating.toFixed(1)}` : null].filter(Boolean).join(' · ') })] }));
    if (kodi)
        return _jsx(Link, { className: "pl-tile dim", to: watchUrl(f.id, label), title: `${label}: plays in Kodi only; open it for the TV, VLC or a download`, children: body });
    return _jsx(Link, { className: "pl-tile", to: watchUrl(f.id, label), title: `Play ${label}`, children: body });
}
function ShowTile({ s }) {
    return (_jsxs(Link, { className: "pl-tile", to: `/player?${new URLSearchParams({ show: s.folder })}`, title: s.title, children: [_jsxs("span", { className: "pl-cover", children: [_jsx(Art, { path: s.poster, title: s.title }), s.watched === s.episodes && _jsx("span", { className: "pl-tick", title: "All watched", "aria-label": "All watched", children: "\u2713" })] }), _jsx("span", { className: "pl-name", children: s.title }), _jsx("span", { className: "pl-sub", children: [s.year, `${s.episodes} ep.`, s.rating ? `★ ${s.rating.toFixed(1)}` : null].filter(Boolean).join(' · ') })] }));
}
function Grid({ items, view }) {
    const list = view === 'films' ? items.films : items.shows;
    const genres = useMemo(() => [...new Set(list.flatMap((x) => x.genres))].sort(), [list]);
    const { keep, order, bar } = useFilters(genres);
    const films = order(items.films.filter((f) => keep(f, f.watched)));
    const shows = order(items.shows.filter((s) => keep(s, s.watched === s.episodes, s.watched < s.episodes)));
    const shown = view === 'films' ? films.length : shows.length;
    return (_jsxs(_Fragment, { children: [bar, _jsxs("p", { className: "pl-count", children: [shown.toLocaleString('en-GB'), " ", view === 'films' ? (shown === 1 ? 'film' : 'films') : (shown === 1 ? 'show' : 'shows')] }), _jsx("div", { className: "pl-grid", children: view === 'films' ? films.map((f) => _jsx(FilmTile, { f: f }, f.id)) : shows.map((s) => _jsx(ShowTile, { s: s }, s.folder)) })] }));
}
function TestSet() {
    const [items, setItems] = useState(null);
    useEffect(() => { api.playerTestSet().then((r) => setItems(r.items)).catch(() => setItems([])); }, []);
    if (!items)
        return _jsx(Loading, { label: "Loading the test set" });
    if (!items.length)
        return _jsx("p", { className: "pl-empty", children: "No test set yet." });
    return (_jsxs(_Fragment, { children: [_jsx("p", { className: "pl-count", children: "One real file per kind (docs/PLAYER.md). Play each in Firefox, Chrome and Edge." }), _jsx("div", { className: "pl-grid", children: items.map((t) => (_jsxs(Link, { className: "pl-tile", to: watchUrl(t.id, t.kind), title: t.path, children: [_jsxs("span", { className: "pl-cover", children: [_jsx(Art, { path: t.art, title: t.kind }), _jsx(PlayMark, {})] }), _jsx("span", { className: "pl-name", children: t.kind }), _jsx("span", { className: "pl-sub", children: t.name })] }, t.id))) })] }));
}
function ShowView({ folder }) {
    const [show, setShow] = useState(null);
    const [error, setError] = useState(null);
    const [season, setSeason] = useState(undefined);
    useEffect(() => { api.playerShow(folder).then(setShow).catch((e) => setError(e.message)); }, [folder]);
    if (error)
        return _jsx("p", { className: "pl-empty", children: error });
    if (!show)
        return _jsx(Loading, { label: "Loading the show" });
    const seasons = [...new Set(show.episodes.map((e) => e.season))].sort((a, b) => (a ?? 999) - (b ?? 999));
    const current = season === undefined ? (seasons.find((s) => show.episodes.some((e) => e.season === s && !e.watched)) ?? seasons[0]) : season;
    return (_jsxs("div", { className: "pl-show", children: [_jsx("header", { className: "pl-hero", style: show.fanart ? { backgroundImage: `url("${art(show.fanart)}")` } : undefined, children: _jsxs("div", { className: "pl-hero-in", children: [_jsx("span", { className: "pl-hero-poster", children: _jsx(Art, { path: show.poster, title: show.title }) }), _jsxs("div", { children: [_jsx("h1", { children: show.title }), _jsx("p", { className: "pl-sub", children: [show.year, show.genres.join(', '), show.rating ? `★ ${show.rating.toFixed(1)}` : null].filter(Boolean).join(' · ') }), show.plot && _jsx("p", { className: "pl-plot", children: show.plot })] })] }) }), _jsx("div", { className: "pl-seasons", role: "tablist", "aria-label": "Seasons", children: seasons.map((s) => (_jsx("button", { type: "button", role: "tab", "aria-selected": s === current, onClick: () => setSeason(s), children: s == null ? 'Other' : s === 0 ? 'Specials' : `Season ${s}` }, String(s)))) }), current != null && (_jsx("p", { className: "pl-season-tools", children: _jsxs("a", { href: `/api/player/zip?${new URLSearchParams({ folder, season: String(current) })}`, download: true, title: "Every episode of this season as it is, with its subtitles, in one ZIP (for a laptop)", children: ["Download ", current === 0 ? "the specials" : `season ${current}`, " (ZIP)"] }) })), _jsx("ul", { className: "pl-episodes", children: show.episodes.filter((e) => e.season === current).map((e) => {
                    const name = `${code(e.season, e.episodes)}${e.title ? ` · ${e.title}` : ''}`;
                    const inner = (_jsxs(_Fragment, { children: [_jsxs("span", { className: "pl-thumb", children: [_jsx(Art, { path: e.thumb, title: e.title ?? show.title, wide: true }), way(e.play) !== 'kodi' && _jsx(PlayMark, {})] }), _jsxs("span", { className: "pl-ep-text", children: [_jsx("span", { className: "pl-name", children: name }), _jsxs("span", { className: "pl-sub", children: [way(e.play) === 'kodi' ? 'Kodi only' : way(e.play) === 'sound' ? 'Sound in a later step' : '', e.watched ? (way(e.play) === 'native' || way(e.play) === 'unknown' ? 'Watched' : ' · Watched') : ''] })] })] }));
                    return (_jsx("li", { children: way(e.play) === 'kodi' ? _jsx(Link, { className: "pl-ep dim", to: watchUrl(e.id, `${show.title} ${name}`), title: "Plays in Kodi only; open it for the TV, VLC or a download", children: inner })
                            : _jsx(Link, { className: "pl-ep", to: watchUrl(e.id, `${show.title} ${name}`), children: inner }) }, e.id));
                }) })] }));
}
function Browse({ view, show }) {
    const [items, setItems] = useState(null);
    const [error, setError] = useState(null);
    useEffect(() => { api.playerItems().then(setItems).catch((e) => setError(e.message)); }, []);
    const nav = [['films', 'Films'], ['tv', 'TV'], ['test', 'Test set']];
    return (_jsxs("div", { className: "pl", children: [_jsxs("aside", { className: "pl-side", "aria-label": "Player", children: [_jsxs(Link, { to: "/", className: "pl-brand", title: "Back to muthur", children: ["muthur ", _jsx("span", { children: "\u00B7 watch" })] }), _jsx("nav", { className: "pl-nav", children: nav.map(([v, label]) => (_jsx(Link, { to: v === 'films' ? '/player' : `/player?view=${v}`, "aria-current": !show && view === v ? 'page' : undefined, children: label }, v))) })] }), _jsxs("main", { className: "pl-main", id: "main", children: [error && _jsx("p", { className: "pl-empty", children: error }), show ? _jsx(ShowView, { folder: show }) : view === 'test' ? _jsx(TestSet, {}) : items ? _jsx(Grid, { items: items, view: view }) : !error && _jsx(Loading, { label: "Loading the library" })] })] }));
}
// ---- open with, download ------------------------------------------------------------------------
// A small menu beside Play (decided 26 Oct): the TV, the phone's own player, the PC's own player, the share path, and
// downloads. A page can't see which players are installed, so each entry simply works or does nothing visible.
const ANDROID = /android/i.test(navigator.userAgent);
const WINDOWS = /windows/i.test(navigator.userAgent);
function OpenMenu({ id, onNote, onFind }) {
    const [open, setOpen] = useState(false);
    const [links, setLinks] = useState(null);
    const [failed, setFailed] = useState(null);
    useEffect(() => {
        if (open && !links)
            api.playerLinks(id).then(setLinks).catch((e) => setFailed(e.message));
    }, [open, links, id]);
    const abs = (path) => new URL(path, location.origin).href;
    // Android: VLC by name (it takes the .srt along), or any app that plays video (the phone asks which).
    const intent = (pkg) => {
        if (!links)
            return '#';
        const u = new URL(links.stream, location.origin);
        const sub = links.subtitles.find((s) => s.lang === 'en' && !s.forced) ?? links.subtitles[0];
        const extras = [`S.title=${encodeURIComponent(links.name)}`, ...(sub && pkg ? [`S.subtitles_location=${encodeURIComponent(abs(sub.url))}`] : [])];
        return `intent://${u.host}${u.pathname}${u.search}#Intent;scheme=${u.protocol.replace(':', '')};type=video/*;${pkg ? `package=${pkg};` : ''}${extras.join(';')};end`;
    };
    const copy = (text, what) => navigator.clipboard.writeText(text).then(() => onNote(`${what} copied.`), () => onNote(text));
    const tv = () => {
        setOpen(false);
        onNote('Starting on the TV… (if Kodi isn’t running, muthur wakes it first: up to a minute)', true);
        api.playerTv(id).then((r) => onNote(`Playing on ${r.device}.`)).catch((e) => onNote(e.message));
    };
    return (_jsxs("span", { className: "pl-menu", children: [_jsx("button", { type: "button", className: "pl-btn", "aria-haspopup": "menu", "aria-expanded": open, onClick: () => setOpen(!open), title: "Open with, download", children: "\u22EF" }), open && (_jsxs("span", { className: "pl-menu-list", role: "menu", children: [failed && _jsx("span", { className: "pl-menu-note", children: failed }), !links && !failed && _jsx("span", { className: "pl-menu-note", children: "Loading\u2026" }), links && (_jsxs(_Fragment, { children: [links.tv && _jsx("button", { type: "button", role: "menuitem", onClick: tv, children: "Play on the TV" }), ANDROID && _jsx("a", { role: "menuitem", href: intent('org.videolan.vlc'), children: "Open in VLC" }), ANDROID && _jsx("a", { role: "menuitem", href: intent(null), children: "Open in another app" }), !ANDROID && (_jsx("a", { role: "menuitem", href: `/api/player/video/${id}/playlist.m3u${WINDOWS ? '?windows=1' : ''}`, download: true, children: "Open in your own player (.m3u)" })), _jsx("button", { type: "button", role: "menuitem", onClick: () => { setOpen(false); onFind(); }, children: "Find subtitles" }), links.share && _jsx("button", { type: "button", role: "menuitem", onClick: () => copy(WINDOWS ? links.share.unc : links.share.smb, 'Path'), children: "Copy path" }), _jsx("button", { type: "button", role: "menuitem", onClick: () => copy(abs(links.stream), 'Link (12 hours)'), children: "Copy link" }), _jsx("span", { className: "pl-menu-sep" }), _jsx("a", { role: "menuitem", href: `/api/player/video/${id}?download=1`, download: true, children: "Download video" }), links.subtitles.map((s) => (_jsxs("a", { role: "menuitem", href: `${s.url}&download=1`, download: true, children: ["Download subtitles: ", s.label] }, s.name)))] }))] }))] }));
}
// ---- watching -------------------------------------------------------------------------------
function Watch({ id, title, mute = false }) {
    const box = useRef(null);
    const video = useRef(null);
    const [info, setInfo] = useState(null);
    const [error, setError] = useState(null);
    const [full, setFull] = useState(false);
    const [cue, setCue] = useState(() => {
        try {
            return localStorage.getItem('muthur.cue') || 'm';
        }
        catch {
            return 'm';
        }
    });
    const nextCue = () => {
        const n = cue === 's' ? 'm' : cue === 'm' ? 'l' : 's';
        setCue(n);
        try {
            localStorage.setItem('muthur.cue', n);
        }
        catch { /* the size just isn't remembered */ }
    };
    useEffect(() => { api.playerInfo(id).then(setInfo).catch((e) => setError(e.message)); }, [id]);
    // The subtitle files beside the video; it grows when muthur copies subtitles out of the file (decided 26 Oct).
    const [subList, setSubList] = useState([]);
    const [subNote, setSubNote] = useState(null);
    const [subProgress, setSubProgress] = useState(null);
    const [flash, setFlash] = useState(null); // what an Open-with entry just did
    const flashTimer = useRef(0);
    const say = (text, ms = 12000) => {
        setFlash(text);
        window.clearTimeout(flashTimer.current);
        flashTimer.current = window.setTimeout(() => setFlash(null), ms);
    };
    // OpenSubtitles' list over the film, to pick from (⋯ Find subtitles, or opened by itself, below).
    const [finding, setFinding] = useState(false);
    // No full subtitles on the share (Valerian, Casino Royale, Ford v Ferrari, 26 Oct): muthur looks on OpenSubtitles
    // while the film waits. One made for this exact file (in sync) is fetched and switched on by itself; otherwise the
    // list opens to choose from. When nothing turns up, the player says what there is, so the film doesn't look broken.
    useEffect(() => {
        if (!info || info.extractable.length || info.subtitles.some((s) => !s.forced))
            return;
        const forced = info.subtitles.find((s) => s.forced);
        const f = forced ? info.forcedLines[forced.name] : null;
        const at = (s) => (s == null ? '' : `, the first at ${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`);
        const why = f && f.lines
            ? `Only forced subtitles: ${f.lines} ${f.lines === 1 ? 'line' : 'lines'} for the parts in another language${at(f.first)}.`
            : info.pictureSubs
                ? `Subtitles only as pictures inside the file (${info.pictureSubs} ${info.pictureSubs === 1 ? 'track' : 'tracks'}): a browser can’t show those.`
                : info.adsOnly.length ? 'The subtitle file beside this video only holds the download site’s advertisements.'
                    : 'No subtitles beside this video.';
        let stop = false;
        holding.current = true;
        video.current?.pause();
        setSubNote('Looking for subtitles on OpenSubtitles…');
        setSubProgress(0);
        api.subtitleSearch(info.path).then(async (d) => {
            if (stop)
                return;
            const best = d.results.find((s) => s.hashMatch && s.language === 'en' && !s.forced && !s.machineTranslated && !s.aiTranslated);
            if (best && !info.dryRun) {
                setSubNote('Fetching the subtitles made for this exact file…');
                await api.subtitleSave(info.path, best.fileId, best.language);
                const fresh = await api.playerInfo(id);
                if (!stop) {
                    setSubList(fresh.subtitles);
                    say('Subtitles from OpenSubtitles, made for this exact file.', 6000);
                }
            }
            else if (d.count) {
                say(`${why} OpenSubtitles has ${d.count}: choose one.`);
                setFinding(true);
                return; // the film waits while the list is open
            }
            else {
                say(`${why} OpenSubtitles has none for this film either.`);
            }
            release();
        }).catch((e) => { if (!stop) {
            say(`${why} ${e.message}`);
            release();
        } })
            .finally(() => { if (!stop) {
            setSubNote(null);
            setSubProgress(null);
        } });
        return () => { stop = true; holding.current = false; };
    }, [info]);
    useEffect(() => { if (info)
        setSubList(info.subtitles); }, [info]);
    useEffect(() => {
        if (!info || !info.extractable.length)
            return;
        if (info.dryRun) {
            setSubNote('This video has subtitles inside; muthur copies them out beside it, but not while dry run is on.');
            return;
        }
        let stop = false;
        setSubNote('Copying the subtitles out of the file…');
        holding.current = true; // the film waits for its subtitles, then starts by itself
        video.current?.pause();
        setSubProgress(0);
        api.playerExtract(id).then(async () => {
            // ffmpeg reads the whole film: the job says how far (seconds read of the film), shown as a bar.
            for (let i = 0; i < 1200 && !stop; i++) {
                await new Promise((r) => setTimeout(r, 1500));
                const job = await api.job().catch(() => null);
                if (job?.name === 'subtitles-extract' && job.running) {
                    if (!stop) {
                        setSubProgress(job.total ? job.done / job.total : 0);
                        setSubNote(job.queued ? 'Subtitles: waiting for another job to finish…' : 'Copying the subtitles out of the file…');
                    }
                    continue;
                }
                const fresh = await api.playerInfo(id);
                if (!stop) {
                    if (fresh.subtitles.length > info.subtitles.length)
                        setSubList(fresh.subtitles);
                    else if (job?.error)
                        setSubNote(`The subtitles couldn’t be copied out: ${job.error}`);
                    setSubProgress(null);
                    if (!job?.error)
                        setSubNote(null);
                    release();
                }
                return;
            }
            if (!stop)
                release();
        }).catch((e) => {
            if (!stop) {
                setSubProgress(null);
                setSubNote(`The subtitles couldn’t be copied out: ${e.message}`);
                release();
            }
        });
        return () => { stop = true; holding.current = false; };
    }, [info, id]);
    // While the subtitles are copied the film waits (autoplay is paused at once); then it starts by itself, with or
    // without them (asked for on 26 Oct).
    const holding = useRef(false);
    const release = () => {
        holding.current = false;
        window.setTimeout(() => void video.current?.play().catch(() => undefined), 400); // after the new tracks are in
    };
    useEffect(() => {
        const v = video.current;
        if (!v)
            return;
        const hold = () => { if (holding.current)
            v.pause(); };
        v.addEventListener('play', hold);
        return () => v.removeEventListener('play', hold);
    }, [info]);
    useEffect(() => {
        const onFull = () => setFull(document.fullscreenElement === box.current);
        document.addEventListener('fullscreenchange', onFull);
        return () => document.removeEventListener('fullscreenchange', onFull);
    }, []);
    const back = () => (history.length > 1 ? history.back() : navigate('/player'));
    const toggleFull = () => (document.fullscreenElement ? document.exitFullscreen() : box.current?.requestFullscreen());
    useEffect(() => {
        const onKey = (e) => {
            const v = video.current;
            if (!v || e.target instanceof HTMLInputElement)
                return;
            if (e.key === 'f' || e.key === 'F')
                toggleFull();
            else if (e.key === 'm' || e.key === 'M')
                v.muted = !v.muted;
            else if (e.key === 'ArrowRight' && e.target === document.body)
                v.currentTime += 10;
            else if (e.key === 'ArrowLeft' && e.target === document.body)
                v.currentTime -= 10;
            else if (e.key === ' ' && e.target === document.body) {
                e.preventDefault();
                if (v.paused)
                    v.play();
                else
                    v.pause();
            }
            else if (e.key === 'Escape' && !document.fullscreenElement)
                back();
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    });
    useEffect(() => { document.title = `${title} · muthur`; }, [title]);
    const how = info ? way(info.play) : null;
    // Repack in the browser (docs/PLAYER.md §4) when the sound needs decoding, for every MKV in Firefox (its MKV reader
    // stutters on some), and when the original-language track isn't the file's default; otherwise the file plays directly.
    const defaultAudio = info?.facts ? Math.max(0, info.facts.audio.findIndex((a) => a.default)) : 0;
    const repack = Boolean(info && how !== 'kodi' && MSE
        && (how === 'sound' || (!HI10 && info.facts?.container === '.mkv') || (info.audio != null && info.audio !== defaultAudio)));
    const src = `/api/player/video/${id}`;
    useEffect(() => {
        if (!repack || !info || !video.current)
            return;
        let engine = null;
        let gone = false;
        import('./repack').then(({ Repack }) => {
            if (gone || !video.current)
                return;
            const r = new Repack(video.current, src, { audio: info.audio, onError: (m) => setError(`Repacking stopped: ${m}`) });
            engine = r;
            r.start().catch((e) => setError(`Repacking failed: ${e.message}`));
        }).catch((e) => setError(`The repacker didn’t load: ${e.message}`));
        return () => { gone = true; engine?.destroy(); };
    }, [repack, info, src]);
    const note = info && how ? (how === 'kodi' && info.play.endsWith('-hi10') ? 'Firefox doesn’t play this video (H.264 in 10-bit): Chrome, Edge and Kodi do.' : PLAY_NOTE[how]) : null;
    const subs = subList;
    // On by default: full English; else a file whose name gives no language (in this library nearly always English); else
    // English forced subtitles, which only translate the lines in another language (Valerian's aliens) and belong on.
    const firstEnglish = [subs.findIndex((s) => s.lang === 'en' && !s.forced), subs.findIndex((s) => s.lang === 'und' && !s.forced),
        subs.findIndex((s) => (s.lang === 'en' || s.lang === 'und') && s.forced)].find((i) => i >= 0) ?? -1;
    // Which subtitles show. Subtitles the browser recognises inside the file itself come first (English first): they
    // belong to this video (none do in Chrome or Firefox today, measured 26 Oct). Else the file beside it chosen above;
    // a track added after the video loaded isn't switched on by its default attribute, so it is switched on here. Once
    // per set of subtitles: what the reader picks in the CC menu afterwards stays.
    useEffect(() => {
        const v = video.current;
        if (!v)
            return;
        let done = false;
        const choose = () => {
            if (done)
                return;
            const ours = new Set([...v.querySelectorAll('track')].map((el) => el.track));
            const inside = [...v.textTracks].filter((t) => !ours.has(t) && (t.kind === 'subtitles' || t.kind === 'captions'));
            const pick = inside.find((t) => t.language.startsWith('en')) ?? inside[0]
                ?? (firstEnglish >= 0 ? v.querySelectorAll('track')[firstEnglish]?.track : undefined);
            if (!pick)
                return;
            for (const t of v.textTracks)
                if (t !== pick && t.mode === 'showing')
                    t.mode = 'disabled';
            pick.mode = 'showing';
            done = inside.length > 0 || v.readyState >= 1;
        };
        const t = setTimeout(choose, 300);
        v.addEventListener('loadedmetadata', choose);
        v.textTracks.addEventListener('addtrack', choose);
        return () => { clearTimeout(t); v.removeEventListener('loadedmetadata', choose); v.textTracks.removeEventListener('addtrack', choose); };
    }, [subs, firstEnglish]);
    return (_jsxs("div", { className: `pl-watch${full ? ' full' : ''}${cue === 'm' ? '' : ` cue-${cue}`}`, ref: box, children: [error && _jsx("p", { className: "pl-watch-msg", children: error }), info && how !== 'kodi' && (_jsx("video", { ref: video, src: repack ? undefined : src, controls: true, autoPlay: true, playsInline: true, preload: "auto", muted: mute, children: subs.map((s, i) => (_jsx("track", { kind: "subtitles", src: `/api/player/video/${id}/subtitles/${encodeURIComponent(s.name)}`, srcLang: s.lang === 'und' ? undefined : s.lang, label: s.label, default: i === firstEnglish }, s.name))) })), _jsxs("div", { className: "pl-watch-top", children: [_jsx("button", { type: "button", className: "pl-btn", onClick: back, "aria-label": "Back", children: "\u2190" }), _jsx("span", { className: "pl-watch-title", title: info?.path, children: title }), info && how !== 'kodi' && _jsx("span", { className: "pl-watch-how", title: "How this video plays", children: repack ? 'repacked in the browser' : 'direct' }), _jsx(OpenMenu, { id: id, onNote: (t, stay) => { window.clearTimeout(flashTimer.current); setFlash(t); if (!stay)
                            flashTimer.current = window.setTimeout(() => setFlash(null), 5000); }, onFind: () => { holding.current = true; video.current?.pause(); setFinding(true); } }), subs.length > 0 && (_jsx("button", { type: "button", className: "pl-btn", onClick: nextCue, title: `Subtitle size: ${cue === 's' ? 'small' : cue === 'm' ? 'medium' : 'large'}`, "aria-label": "Subtitle size", children: cue === 's' ? 'a' : cue === 'm' ? 'Aa' : 'AA' })), _jsx("button", { type: "button", className: "pl-btn", onClick: toggleFull, "aria-label": full ? 'Leave full screen' : 'Full screen', children: full ? '⤡' : '⤢' })] }), note && _jsx("p", { className: `pl-watch-msg${how === 'kodi' ? '' : ' corner'}`, children: note }), finding && info && (_jsxs("aside", { className: "panel pl-subpanel", "aria-label": "Subtitles from OpenSubtitles", children: [_jsxs("div", { className: "panel-head", children: [_jsx("h2", { children: "Subtitles from OpenSubtitles" }), _jsx("button", { type: "button", className: "btn btn-secondary btn-sm", onClick: () => { setFinding(false); release(); }, children: "Close" })] }), _jsx(SubtitleSearch, { path: info.path, onSaved: () => {
                            api.playerInfo(id).then((fresh) => { setSubList(fresh.subtitles); setFinding(false); release(); }).catch(() => undefined);
                        } })] })), flash && _jsx("p", { className: "pl-watch-msg corner", role: "status", children: flash }), subNote && !note && !flash && (_jsxs("div", { className: "pl-watch-msg corner", role: "status", children: [_jsxs("span", { children: [subNote, subProgress != null && subProgress > 0 ? ` ${Math.round(subProgress * 100)}%` : ""] }), subProgress != null && _jsx("span", { className: `pl-progress${subProgress > 0 ? "" : " busy"}`, children: _jsx("span", { style: { width: `${Math.max(4, subProgress * 100)}%` } }) })] })), !info && !error && _jsx("p", { className: "pl-watch-msg", children: "Loading\u2026" })] }));
}
export default function PlayerApp() {
    const { path, search } = useLocation();
    const q = new URLSearchParams(search);
    if (path === '/player/watch' && q.get('id'))
        return _jsx(Watch, { id: q.get('id'), title: q.get('t') ?? 'Video', mute: q.get('mute') === '1' });
    const view = (q.get('view') ?? 'films');
    return _jsx(Browse, { view: ['films', 'tv', 'test'].includes(view) ? view : 'films', show: q.get('show') });
}
