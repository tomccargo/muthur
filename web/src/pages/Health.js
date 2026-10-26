import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useRef, useState } from 'react';
import { QuarantinePanel } from './Quarantine';
import { TitleCard } from './Review';
import { api } from '../api';
import { Dot, JobError, Loading } from '../components';
import { count, libraryPath, middle, when } from '../labels';
import { Link } from '../nav';
// What each fix does to the reader's files (DESIGN.md §1.7: name what happens, not the record).
const FIX = {
    'imdb-data': { title: 'Download IMDb scores for shows that have none yet', what: 'Then muthur’s own NFOs get their scores; other NFOs follow as “Add IMDb scores”.' },
    'imdb-scores': { title: 'Add IMDb scores to NFOs', what: 'Adds IMDb’s score as the one Kodi shows. Other ratings in the NFO stay; a copy of each old NFO is kept. Kodi re-reads each item.' },
    'episode-nfos': { title: 'Write NFOs for episodes that have none', what: 'Writes an NFO (and a thumbnail where missing) from TMDB, with IMDb’s score. Only for seasons TMDB numbers the way your library does.' },
    'show-nfos': { title: 'Write tvshow.nfo for show folders that have none', what: 'Writes the show’s NFO, poster, fanart and logo from TMDB where they’re missing.' },
    'film-nfos': { title: 'Write NFOs for films that have none', what: 'Writes the NFO, poster, fanart and logo from TMDB where missing, for films muthur recognises with certainty by name, year and length.' },
    renames: { title: 'Rename episodes to the library’s naming', what: 'Show - S01E02 - TMDB’s title, with the NFO, thumbnail and subtitles. Only while Kodi is on: it keeps each episode’s watched status.' },
    'film-renames': { title: 'Rename films to the library’s naming', what: 'Title (Year)/Title (Year), from the NFO, with the artwork and subtitles; download-site notes go to quarantine. Only while Kodi is on.' },
    posters: { title: 'Replace missing and poor posters', what: 'TMDB’s poster where there is none, or one under 500 pixels wide or not poster-shaped. The old one is kept; Kodi re-reads each item.' },
    subtitles: { title: 'Put subtitles where Kodi finds them', what: 'English goes beside the video under its name (Dutch only when there is no English); other languages, extra copies and Dutch next to English go to quarantine.' },
    leftovers: { title: 'Move leftover files to quarantine', what: 'Tracker notes, Thumbs.db, and NFOs, thumbnails or subtitles of videos that are gone.' },
    'empty-films': { title: 'Move film folders without a video to quarantine', what: 'Folders that only hold an NFO or artwork.' },
    'kodi-entries': { title: 'Remove old entries from Kodi', what: 'Films and episodes Kodi lists twice: once where the video was before a rename, or twice for the same file. The entry that stays gets the watched status first. Only while Kodi is on; no files change.' },
    'subtitle-timing': { title: 'Stretch subtitles that are out of sync', what: 'Subtitle files from another release: too fast, too slow or shifted, measured against the subtitles inside the video. A stretched copy takes their place; the original goes to quarantine.' },
    'subtitle-misfit': { title: 'Move subtitles that don’t fit to quarantine', what: 'Subtitle files that match the video nowhere, even stretched (another cut of the film).' },
    'show-rematch': { title: 'Match shows to the show their episodes are', what: 'A folder whose episode titles are another TMDB show’s (the US Shameless in a folder matched to the UK one). Its tvshow.nfo, episode NFOs, thumbnails and artwork become that show’s (the old ones are kept); episodes of the old show go to its own folder, or to quarantine when it has them already. Kodi re-reads each item.' },
    extras: { title: 'Move extras to the show’s Extras folder', what: 'Interviews, featurettes, openings and the like that sit between the episodes. Kodi doesn’t list them as episodes; in Extras its Extras add-on finds them. Nothing else changes.' },
};
const ORDER = ['imdb-data', 'imdb-scores', 'show-rematch', 'episode-nfos', 'show-nfos', 'film-nfos', 'posters', 'subtitles', 'subtitle-timing', 'subtitle-misfit', 'renames', 'film-renames', 'kodi-entries', 'extras', 'leftovers', 'empty-films'];
// The fixes in three groups, with "Questions for you" between the second and third (DESIGN.md §1.11): a few titled groups read better than eleven tiles.
export const GROUPS = [
    { id: 'scores', title: 'IMDb scores', kinds: ['imdb-data', 'imdb-scores'] }, // shown first, then Missing in Kodi, the questions, Tidy up
    { id: 'kodi', title: 'Missing in Kodi', kinds: ['show-rematch', 'episode-nfos', 'show-nfos', 'film-nfos', 'posters', 'subtitles'] },
    { id: 'tidy', title: 'Tidy up', kinds: ['renames', 'film-renames', 'subtitle-timing', 'subtitle-misfit', 'kodi-entries', 'extras', 'leftovers', 'empty-films'] },
];
// The answers to a question about an episode's number (or a season's): which episode it is, that its number is
// right, or the show's page; leaving it as is stays possible.
function EpisodeAnswers({ q, kind, onDone, leave }) {
    const [busy, setBusy] = useState(null);
    const [error, setError] = useState(null);
    const [picker, setPicker] = useState(null);
    const [season, setSeason] = useState(Number((q.path.match(/S(\d{1,3})E\d/i) ?? [])[1] ?? q.season ?? 1));
    const [episode, setEpisode] = useState(null);
    const folder = q.path.split('/')[1] ?? '';
    const run = (key, request, text) => {
        setBusy(key);
        setError(null);
        request().then(() => onDone(text)).catch((e) => setError(e.message)).finally(() => setBusy(null));
    };
    const load = (s) => {
        if (!q.tmdb)
            return;
        setSeason(s);
        setEpisode(null);
        api.season(q.tmdb, s).then(setPicker).catch((e) => setError(e.message));
    };
    const picked = picker?.episodes.find((x) => x.episode === episode);
    // TMDB's other orders for the show (DVD, production…), with how many of its files each fits.
    const [orders, setOrders] = useState(null);
    const loadOrders = () => {
        setBusy('orders');
        api.libraryOrders(folder).then(setOrders).catch((e) => setError(e.message)).finally(() => setBusy(null));
    };
    return (_jsxs("span", { style: { display: 'flex', flexDirection: 'column', gap: 6 }, children: [_jsxs("span", { className: "actions", children: [kind === 'seasons' && !orders && (_jsx("button", { type: "button", className: "btn btn-secondary btn-sm", "aria-busy": busy === 'orders', onClick: loadOrders, title: "TMDB keeps other orders for many shows (DVD, production): one may match your files", children: "Use another order" })), kind === 'numbers' && q.tmdb && !picker && _jsx("button", { type: "button", className: "btn btn-secondary btn-sm", onClick: () => load(season), children: "Which episode is it?" }), kind === 'numbers' && !q.noNumber && (_jsx("button", { type: "button", className: "btn btn-secondary btn-sm", "aria-busy": busy === 'trust', title: "Its NFO and score are written by this number at the next fix; nothing is renamed by this", onClick: () => run('trust', () => api.trustNumber(q.path), `${q.show ?? folder}: the number of ${q.path.split('/').pop()} is taken as right.`), children: "The number is right" })), _jsx(Link, { to: `/library?${new URLSearchParams({ folder })}`, className: "btn btn-ghost btn-sm", children: "Open the show" }), _jsx("button", { type: "button", className: "btn-link small", onClick: leave, children: "Leave as is" })] }), picker && (_jsxs("span", { className: "actions", children: [_jsx("select", { className: "field", "aria-label": "Season", value: season, onChange: (e) => load(Number(e.target.value)), style: { width: 'auto' }, children: picker.seasons.map((s) => _jsx("option", { value: s.season, children: s.season === 0 ? 'Specials' : `Season ${s.season}` }, s.season)) }), _jsxs("select", { className: "field", "aria-label": "Episode", value: episode ?? '', onChange: (e) => setEpisode(Number(e.target.value) || null), style: { width: 'auto', maxWidth: '100%' }, children: [_jsx("option", { value: "", children: "Which episode?" }), picker.episodes.map((x) => _jsxs("option", { value: x.episode, children: [`E${String(x.episode).padStart(2, '0')}`, " \u00B7 ", x.title ?? '—'] }, x.episode))] }), picked && (_jsxs("button", { type: "button", className: "btn btn-secondary btn-sm", "aria-busy": busy === 'rename', onClick: () => run('rename', () => api.episodeRename(q.path, { season, episode: picked.episode }), `Renaming to S${String(season).padStart(2, '0')}E${String(picked.episode).padStart(2, '0')} “${picked.title}”: the bar at the top shows it.`), children: ["It\u2019s S", String(season).padStart(2, '0'), "E", String(picked.episode).padStart(2, '0'), " \u201C", picked.title, "\u201D"] }))] })), picker && _jsx("span", { className: "small muted", children: "The file gets that number and title, and its NFO describes that episode. Kodi keeps the watched status (Kodi has to be on)." }), orders && (orders.orders.length === 0
                ? _jsxs("span", { className: "small muted", children: ["TMDB has no other order for ", q.show ?? folder, "."] })
                : (_jsx("ul", { className: "rows", children: orders.orders.map((o) => (_jsxs("li", { children: [_jsxs("span", { style: { display: 'flex', flexDirection: 'column', minWidth: 0 }, children: [_jsx("strong", { children: o.name }), _jsxs("span", { className: "small muted", children: [o.kind, " order \u00B7 ", count(o.seasons, 'season'), " \u00B7 ", count(o.episodes, 'episode'), " \u00B7 fits ", o.fits, " of your ", count(orders.files, 'file')] })] }), orders.current === o.id
                                ? _jsx("button", { type: "button", className: "btn btn-ghost btn-sm", "aria-busy": busy === 'own', onClick: () => run('own', () => api.setOrder(folder, null), `${q.show ?? folder} is read by TMDB’s own order again.`), children: "Back to TMDB\u2019s order" })
                                : _jsx("button", { type: "button", className: "btn btn-secondary btn-sm", "aria-busy": busy === o.id, onClick: () => run(o.id, () => api.setOrder(folder, o.id), `${q.show ?? folder} is read by “${o.name}” now; its fixes and questions are updated.`), children: "Use this order" })] }, o.id))) }))), error && _jsx("span", { className: "banner banner-error", role: "alert", children: error })] }));
}
// 'TV/The Office (US)' for a question inside a show's folder; null for anything else.
const showOf = (q) => (q && q.path.startsWith('TV/') && q.path.split('/').length > 1 ? q.path.split('/').slice(0, 2).join('/') : null);
const QUESTIONS = {
    seasons: 'Seasons numbered differently from TMDB',
    numbers: 'Episodes whose number can’t be trusted',
    shows: 'Shows muthur can’t find on TMDB',
    films: 'Films without an NFO',
};
// "Which is it?" for a show or film muthur can't place: a TMDB search right in the list.
function Chooser({ kind, path, busy, onDone }) {
    const name = path.split('/').filter(Boolean)[kind === 'tv' ? 1 : path.split('/').length - 1] ?? path;
    const [open, setOpen] = useState(false);
    const [query, setQuery] = useState(name.replace(/\.[a-z0-9]{2,4}$/i, '').replace(/[._]+/g, ' '));
    const [cards, setCards] = useState(null);
    const [picked, setPicked] = useState(null);
    const [error, setError] = useState(null);
    if (!open)
        return _jsx("button", { className: "btn-link small", type: "button", style: { alignSelf: 'flex-start' }, onClick: () => setOpen(true), children: "Which is it?" });
    const search = () => { setError(null); api.search(kind, query).then((r) => { setCards(r.results); setPicked(null); }).catch((e) => setError(e.message)); };
    const choose = () => {
        if (!picked)
            return;
        api.chooseForLibrary(kind, path, picked.tmdbId)
            .then((r) => onDone(`${picked.title}${picked.year ? ` (${picked.year})` : ''}: ${count(Object.values(r.fixes).reduce((a, b) => a + (b ?? 0), 0), 'fix', 'fixes')} added${r.questions ? `, ${count(r.questions, 'question')} left` : ''}.`))
            .catch((e) => setError(e.message));
    };
    return (_jsxs("div", { style: { display: 'flex', flexDirection: 'column', gap: 8, paddingTop: 6 }, children: [_jsxs("form", { className: "inline", onSubmit: (e) => { e.preventDefault(); search(); }, children: [_jsx("input", { className: "field", "aria-label": "Title", value: query, onChange: (e) => setQuery(e.target.value) }), _jsx("button", { className: "btn btn-secondary btn-sm", type: "submit", disabled: !query.trim(), children: "Search TMDB" })] }), cards && (cards.length ? (_jsx("div", { className: "cards", children: cards.slice(0, 6).map((c) => _jsx(TitleCard, { card: c, pressed: picked?.tmdbId === c.tmdbId, onPick: () => setPicked(c) }, c.tmdbId)) })) : _jsx("p", { className: "hint", children: "Nothing found; try another spelling." })), error && _jsx("div", { className: "banner banner-error", role: "alert", children: error }), picked && _jsxs("button", { className: "btn btn-secondary btn-sm", type: "button", disabled: busy, "aria-busy": busy, style: { alignSelf: 'flex-start' }, onClick: choose, children: ["It\u2019s ", picked.title, picked.year ? ` (${picked.year})` : ''] })] }));
}
// Videos on disk more than once, by name: its own panel, because only the reader can choose the copy to keep
// (DESIGN.md §1.11). The choosing happens in Duplicates.
function DuplicatesPanel({ groups }) {
    if (!groups.length)
        return null;
    const films = groups.filter((g) => g.kind === 'film');
    const shows = new Map();
    for (const g of groups.filter((x) => x.kind === 'episode')) {
        shows.set(g.title, [...(shows.get(g.title) ?? []), g.label.slice(g.title.length).trim()]);
    }
    const episodes = groups.length - films.length;
    return (_jsxs("section", { id: "duplicates", className: "panel", "aria-labelledby": "dups-h", style: { display: 'flex', flexDirection: 'column', gap: 8 }, children: [_jsxs("div", { className: "panel-head", style: { marginBottom: 0 }, children: [_jsx("h2", { id: "dups-h", children: "Duplicates" }), _jsx("span", { className: "num", children: groups.length.toLocaleString('en-GB') })] }), _jsx("span", { className: "small muted", children: "On disk more than once. You choose the copy that stays; the others go to quarantine, and Kodi keeps the watched status." }), _jsxs("ul", { className: "rows", children: [films.length > 0 && (_jsxs("li", { style: { flexDirection: 'column', alignItems: 'stretch', gap: 2 }, children: [_jsx("strong", { children: count(films.length, 'film') }), _jsx("span", { className: "small", children: films.map((g) => g.label).join(' · ') })] })), episodes > 0 && (_jsxs("li", { style: { flexDirection: 'column', alignItems: 'stretch', gap: 2 }, children: [_jsx("strong", { children: count(episodes, 'episode') }), _jsx("span", { className: "small", children: [...shows].map(([show, eps]) => `${show} ${eps.join(', ')}`).join(' · ') })] }))] }), _jsx("span", { className: "actions", children: _jsx(Link, { to: "/duplicates", className: "btn btn-secondary", children: "Choose which copy to keep" }) })] }));
}
export function HealthPage({ status, refresh }) {
    const [data, setData] = useState(null);
    const [chosen, setChosen] = useState(new Set());
    const [asking, setAsking] = useState(false);
    const [last, setLast] = useState(null);
    const [error, setError] = useState(null);
    const [note, setNote] = useState(null);
    const [showLeft, setShowLeft] = useState(false);
    const running = Boolean(status?.job?.running);
    const leave = (body) => {
        api.leaveQuestions(body).then(() => api.fixes(showLeft)).then(setData).catch((e) => setError(e.message));
    };
    const [dupGroups, setDupGroups] = useState([]);
    useEffect(() => {
        api.fixes(showLeft).then((d) => { setData(d); setChosen(new Set()); }).catch((e) => setError(e.message));
        api.fixesLast().then((r) => setLast('done' in r ? r : null)).catch(() => undefined);
        api.duplicates().then((d) => setDupGroups(d.groups)).catch(() => undefined);
    }, [running, status?.job?.finished, showLeft]);
    // A Dashboard tile opens its own panel here ('/health#tidy'), once the panels are drawn.
    const jumped = useRef(false);
    useEffect(() => {
        const id = location.hash.slice(1);
        if (!data || jumped.current || !id)
            return;
        jumped.current = true;
        document.getElementById(id)?.scrollIntoView({ block: 'start' });
    }, [data]);
    const available = ORDER.filter((k) => (data?.fixes[k]?.count ?? 0) > 0);
    const total = [...chosen].reduce((n, k) => n + (data?.fixes[k]?.count ?? 0), 0);
    const toggle = (k, on) => setChosen((s) => { const n = new Set(s); if (on)
        n.add(k);
    else
        n.delete(k); return n; });
    // The button pressed spins until its request is answered; a job then shows in the job bar (DESIGN.md §7.6).
    const [starting, setStarting] = useState(null);
    const begin = (key, request) => {
        setStarting(key);
        setError(null);
        request().then(refresh).catch((e) => setError(e.message)).finally(() => setStarting(null));
    };
    // An answered question: what happened shows at the top, and the plan is read again (the show was checked again).
    const answered = (text) => { setNote(text); api.fixes(showLeft).then(setData).catch(() => undefined); refresh(); };
    const check = () => begin('check', api.checkFixes);
    const apply = () => { setAsking(false); begin('apply', () => api.applyFixes([...chosen])); };
    // One group of fixes, as a panel (DESIGN.md §1.11).
    const group = (g) => {
        const kinds = g.kinds.filter((k) => available.includes(k));
        if (!kinds.length)
            return null;
        return (_jsxs("section", { id: g.id, className: "panel", "aria-labelledby": `${g.id}-h`, style: { display: 'flex', flexDirection: 'column', gap: 4 }, children: [_jsxs("div", { className: "panel-head", style: { marginBottom: 4 }, children: [_jsx("h2", { id: `${g.id}-h`, children: g.title }), _jsx("span", { className: "num", children: kinds.reduce((n, k) => n + (data.fixes[k]?.count ?? 0), 0).toLocaleString('en-GB') })] }), _jsx("ul", { className: "rows", children: kinds.map((k) => {
                        const f = data.fixes[k];
                        return (_jsxs("li", { style: { flexDirection: 'column', alignItems: 'stretch', gap: 4 }, children: [_jsxs("span", { className: "actions", style: { justifyContent: 'space-between', flexWrap: 'nowrap' }, children: [_jsxs("label", { className: "choice", style: { alignItems: 'center' }, children: [_jsx("input", { type: "checkbox", checked: chosen.has(k), onChange: (e) => toggle(k, e.target.checked) }), _jsx("strong", { children: FIX[k].title })] }), _jsx("span", { className: "num", children: f.count.toLocaleString('en-GB') })] }), _jsx("span", { className: "small muted", children: FIX[k].what }), _jsxs("details", { children: [_jsx("summary", { className: "small", style: { cursor: 'pointer' }, children: "Which" }), _jsxs("ul", { className: "rows", style: { marginTop: 4 }, children: [f.sample.map((x) => (_jsxs("li", { children: [_jsx("span", { className: x.label ? 'small' : 'mono small', title: libraryPath(x.path), style: { minWidth: 0, wordBreak: 'break-all' }, children: x.label ?? middle(libraryPath(x.path), 90) }), _jsx("span", { className: "small muted", children: x.score ? `IMDb ${x.score[0].toFixed(1)}` : x.why ?? '' })] }, x.path))), f.count > f.sample.length && _jsx("li", { children: _jsxs("span", { className: "small muted", children: ["and ", (f.count - f.sample.length).toLocaleString('en-GB'), " more"] }) })] })] })] }, k));
                    }) })] }, g.id));
    };
    return (_jsxs("div", { className: "page", children: [_jsxs("header", { className: "page-head", children: [_jsxs("div", { children: [_jsx("p", { className: "eyebrow", children: "Library health" }), _jsx("h1", { children: "Health" }), _jsx("p", { className: "lede", children: data?.at ? `Checked ${when(data.at)} · daily` : 'Not checked yet' })] }), _jsxs("div", { className: "actions", children: [!asking && _jsx("button", { className: "btn btn-secondary btn-sm", type: "button", "aria-busy": starting === 'check', onClick: check, children: data?.at ? 'Check again' : 'Check the library' }), !asking && (chosen.size > 0
                                ? _jsxs("button", { className: "btn btn-primary", type: "button", disabled: running, onClick: () => setAsking(true), children: ["Apply ", count(total, 'fix', 'fixes')] })
                                : _jsx("button", { className: "btn btn-primary", type: "button", "aria-disabled": "true", title: "Choose fixes first", children: "Apply fixes" }))] })] }), asking && (_jsxs("section", { className: "panel", role: "group", "aria-labelledby": "ask-h", style: { display: 'flex', flexDirection: 'column', gap: 12, borderColor: 'var(--mark)' }, children: [_jsxs("h2", { id: "ask-h", style: { margin: 0, fontSize: '1.15rem', fontWeight: 650 }, children: ["Apply ", count(total, 'fix', 'fixes'), " to the library?"] }), _jsx("ul", { className: "rows", children: [...chosen].map((k) => _jsxs("li", { children: [_jsx("span", { children: FIX[k].title }), _jsx("span", { className: "num", children: data?.fixes[k]?.count.toLocaleString('en-GB') })] }, k)) }), _jsx("p", { className: "hint", children: "Nothing is overwritten or deleted: new files only where none exist, NFO changes with a copy of the old file, removals into quarantine. The whole run can be put back from History." }), _jsxs("div", { className: "actions", style: { justifyContent: 'flex-end' }, children: [_jsx("button", { className: "btn btn-secondary", type: "button", autoFocus: true, onClick: () => setAsking(false), children: "Cancel" }), _jsx("button", { className: "btn btn-primary", type: "button", onClick: apply, children: "Apply them" })] })] })), _jsx(JobError, { job: status?.job }), !data && !error && _jsx(Loading, { label: "Loading the library check" }), error && _jsx("div", { className: "banner banner-error", role: "alert", children: error }), note && _jsx("div", { className: "banner banner-note", role: "status", children: note }), last && !running && status?.job?.name === 'fixes-apply' && (_jsxs("div", { className: `banner ${last.failed.length ? 'banner-warn' : 'banner-note'}`, role: "status", style: { flexDirection: 'column', alignItems: 'stretch' }, children: [_jsxs("span", { className: "status", children: [_jsx(Dot, { kind: last.failed.length ? 'dot-warning' : 'dot-success' }), Object.values(last.done).reduce((a, b) => a + (b ?? 0), 0), " fixed", last.failed.length ? `, ${last.failed.length} didn’t work` : '', ". What changed is in History."] }), last.failed.slice(0, 8).map((f) => _jsxs("span", { className: "small", children: [libraryPath(f.path), ": ", f.why] }, f.path))] })), data?.at && available.length === 0 && (_jsxs("section", { className: "panel", style: { textAlign: 'center', padding: '32px 16px' }, children: [_jsx("h2", { style: { margin: '0 0 6px', fontSize: '1.2rem' }, children: "Nothing muthur can fix on its own" }), _jsx("p", { className: "hint", children: "Anything left needs you; it\u2019s under Questions for you." })] })), group(GROUPS[0]), group(GROUPS[1]), data?.at && (Object.entries(data.manual).some(([, v]) => (v?.count ?? 0) > 0) || data.left > 0) && (_jsxs("section", { id: "questions", className: "panel", "aria-labelledby": "manual-h", style: { display: 'flex', flexDirection: 'column', gap: 12 }, children: [_jsxs("div", { className: "panel-head", style: { marginBottom: 0 }, children: [_jsx("h2", { id: "manual-h", children: showLeft ? 'Left as is' : 'Questions for you' }), data.left > 0 || showLeft
                                ? _jsx("button", { type: "button", className: "btn-link small", onClick: () => setShowLeft(!showLeft), children: showLeft ? 'Show the open questions' : `Show the ${data.left} left as is` })
                                : null] }), !Object.values(data.manual).some((v) => (v?.count ?? 0) > 0) && (_jsx("p", { className: "hint", style: { margin: 0 }, children: showLeft ? 'Nothing is left as is.' : 'No open questions.' })), Object.entries(data.manual).filter(([, v]) => (v?.count ?? 0) > 0).map(([k, v]) => (_jsxs("details", { children: [_jsxs("summary", { style: { cursor: 'pointer' }, children: [_jsx("strong", { children: QUESTIONS[k] ?? k }), " ", _jsx("span", { className: "num muted", children: v.count })] }), _jsxs("ul", { className: "rows", style: { marginTop: 6 }, children: [v.items.map((q, i) => (_jsxs("li", { style: { flexDirection: 'column', gap: 2 }, children: [!showLeft && showOf(q) && showOf(q) !== showOf(v.items[i - 1]) && v.items.filter((x) => showOf(x) === showOf(q)).length > 1 && (_jsxs("span", { className: "actions", style: { justifyContent: 'space-between' }, children: [_jsx("strong", { children: showOf(q).slice(3) }), _jsxs("button", { type: "button", className: "btn-link small", onClick: () => leave({ under: showOf(q) }), children: ["Leave all of ", showOf(q).slice(3), " as is"] })] })), _jsxs("span", { className: "mono small", style: { wordBreak: 'break-all' }, children: [libraryPath(q.path), q.season != null ? ` · season ${q.season}` : ''] }), _jsx("span", { className: "small muted", children: q.why }), (k === 'numbers' || k === 'seasons') && !showLeft
                                                ? _jsx(EpisodeAnswers, { q: q, kind: k, onDone: answered, leave: () => leave({ items: [q] }) })
                                                : (_jsx("span", { className: "actions", children: _jsx("button", { type: "button", className: "btn-link small", onClick: () => leave({ items: [q], back: showLeft }), children: showLeft ? 'Ask again' : 'Leave as is' }) })), (k === 'shows' || k === 'films') && (_jsx(Chooser, { kind: k === 'shows' ? 'tv' : 'movie', path: q.path, busy: running, onDone: answered }))] }, q.path + (q.season ?? '')))), v.count > v.items.length && _jsx("li", { children: _jsxs("span", { className: "small muted", children: ["and ", v.count - v.items.length, " more"] }) })] })] }, k)))] })), _jsx(DuplicatesPanel, { groups: dupGroups }), group(GROUPS[2]), _jsx(QuarantinePanel, { busy: running })] }));
}
