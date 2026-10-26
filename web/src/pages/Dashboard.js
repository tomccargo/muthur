import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from 'react';
import { WatchedPanel } from './Watched';
import { api } from '../api';
import { Dot, JobError, useElapsed } from '../components';
import { count, when } from '../labels';
import { Link } from '../nav';
// The Dashboard is numbers and status: what each panel means is in the docs and Settings, not repeated here.
// Problems keep their sentence and their way out (DESIGN.md §1.5); a panel with nothing to say is left out.
function pathProblem(label, p) {
    if (!p || (p.exists && p.readable))
        return null;
    return _jsxs("li", { children: [_jsx("span", { children: label }), _jsxs("span", { className: "status", children: [_jsx(Dot, { kind: "dot-danger" }), !p.exists ? 'Not found' : 'Can’t be read'] })] }, label);
}
export function Dashboard({ status, error, refresh }) {
    const [message, setMessage] = useState(null);
    const [kodiNote, setKodiNote] = useState(null);
    const [waking, setWaking] = useState(false);
    const counts = status?.inbox.counts ?? {};
    const job = status?.job;
    const tmdb = Boolean(status?.tmdb.configured);
    // A job started while another runs waits its turn (the queue), so nothing here is disabled for being busy.
    const [starting, setStarting] = useState(null);
    const start = (key, fn) => {
        setMessage(null);
        setStarting(key);
        fn().then(refresh).catch((e) => setMessage({ kind: 'error', text: e.message })).finally(() => setStarting(null));
    };
    const wakeFor = useElapsed(waking);
    const scanned = status?.inbox.scannedAt;
    const waiting = (counts.ready ?? 0) + (counts.review ?? 0);
    const k = status?.kodi;
    const sc = status?.scores;
    const device = status?.names.device ?? 'Kodi device';
    const suspicious = counts.suspicious ?? 0;
    const folderProblems = [pathProblem('Finished downloads', status?.paths.downloads), pathProblem('TV', status?.paths.tv),
        pathProblem('Film', status?.paths.film)].filter(Boolean);
    return (_jsxs("div", { className: "page", children: [_jsxs("header", { className: "page-head", children: [_jsxs("div", { children: [_jsx("p", { className: "eyebrow", children: status?.names.nas ?? 'NAS' }), _jsx("h1", { children: "Dashboard" }), _jsx("p", { className: "lede", children: scanned ? `${waiting} to file · checked ${when(scanned)}` : 'Downloads not checked yet' })] }), _jsxs("div", { className: "actions", children: [_jsx(Link, { to: "/player", className: "btn btn-secondary", title: "Watch films and episodes in the browser", children: "Watch" }), tmdb
                                ? _jsx("button", { className: "btn btn-primary", type: "button", "aria-busy": starting === 'scan', onClick: () => start('scan', api.scan), title: "Looks in the downloads folder and works out what each one is. Nothing moves.", children: "Look for new downloads" })
                                : _jsx("button", { className: "btn btn-primary", type: "button", "aria-disabled": "true", title: "Add the TMDB token in Settings first", children: "Look for new downloads" })] })] }), status && _jsx(SetupChecklist, { status: status }), error && _jsxs("div", { className: "banner banner-error", role: "alert", children: ["muthur isn\u2019t answering: ", error] }), message && _jsx("div", { className: `banner banner-${message.kind}`, role: "alert", children: message.text }), suspicious > 0 && (_jsxs("div", { className: "banner banner-error", role: "alert", children: [_jsxs("span", { children: [_jsxs("strong", { children: [suspicious, " suspicious download", suspicious === 1 ? '' : 's'] }), " \u2014 don\u2019t open ", suspicious === 1 ? 'it' : 'them', "."] }), _jsx(Link, { to: "/inbox?show=suspicious", children: "See which" })] })), status && !status.applying && (_jsxs("div", { className: "banner banner-note", children: [_jsxs("span", { className: "status", children: [_jsx(Dot, { kind: "dot-warning" }), "Dry run is on: nothing changes."] }), _jsx(Link, { to: "/settings", children: "Settings" })] })), _jsx(JobError, { job: job }), _jsxs("section", { className: "tiles", "aria-label": "Downloads", children: [_jsxs(Link, { className: "tile", to: "/inbox?show=ready", children: [_jsx("span", { className: "label", children: "Ready" }), _jsx("strong", { children: counts.ready ?? 0 })] }), _jsxs(Link, { className: "tile", to: "/inbox?show=review", children: [_jsx("span", { className: "label", children: "Needs you" }), _jsx("strong", { children: counts.review ?? 0 })] }), _jsxs(Link, { className: "tile", to: "/inbox?show=waiting", children: [_jsx("span", { className: "label", children: "Downloading" }), _jsx("strong", { children: counts.waiting ?? 0 })] }), (counts.packed ?? 0) > 0 && _jsxs(Link, { className: "tile", to: "/inbox?show=packed", children: [_jsx("span", { className: "label", children: "Packed" }), _jsx("strong", { children: counts.packed })] }), _jsxs(Link, { className: "tile", to: "/inbox?show=ignored", children: [_jsx("span", { className: "label", children: "Ignored" }), _jsx("strong", { children: counts.ignored ?? 0 })] })] }), _jsxs("section", { className: "panel", "aria-labelledby": "health-h", children: [_jsxs("div", { className: "panel-head", children: [_jsx("h2", { id: "health-h", children: "Health" }), _jsxs("span", { className: "small muted", children: [status?.library?.at ? `checked ${when(status.library.at)} · ` : '', _jsx(Link, { to: "/health", children: "Open Health" })] })] }), _jsx(LibraryProblems, { status: status })] }), _jsxs("div", { className: "grid-2", children: [_jsxs("section", { className: "panel", "aria-labelledby": "kodi-h", children: [_jsxs("div", { className: "panel-head", children: [_jsxs("h2", { id: "kodi-h", children: ["Kodi on the ", device] }), _jsx(Link, { to: "/settings", className: "small", children: "Settings" })] }), _jsx("p", { style: { margin: '0 0 12px' }, children: k == null ? _jsxs("span", { className: "status", children: [_jsx(Dot, {}), "Not set up"] })
                                    : k.connected ? _jsxs("span", { className: "status", children: [_jsx(Dot, { kind: "dot-success" }), "Connected \u00B7 Kodi ", k.version] })
                                        : _jsxs("span", { className: "status", children: [_jsx(Dot, { kind: "dot-danger" }), k.off ? 'Off (asleep, or Kodi closed)' : k.problem] }) }), _jsxs("div", { className: "actions", children: [k && !k.connected && k.canWake && (_jsx("button", { className: "btn btn-secondary btn-sm", type: "button", disabled: waking, "aria-busy": waking, onClick: () => {
                                            setKodiNote(null);
                                            setWaking(true);
                                            api.wakeShield()
                                                .then(() => { setKodiNote({ kind: 'note', text: `The ${device} is awake and Kodi answers.` }); refresh(); })
                                                .catch((e) => setKodiNote({ kind: 'error', text: e.message }))
                                                .finally(() => setWaking(false));
                                        }, children: waking ? `Waking the ${device}…${wakeFor}` : `Wake the ${device}` })), k?.connected && (_jsx("button", { className: "btn btn-secondary btn-sm", type: "button", onClick: () => {
                                            setKodiNote(null);
                                            api.scanKodi()
                                                .then(() => setKodiNote({ kind: 'note', text: 'Kodi is looking for new files.' }))
                                                .catch((e) => setKodiNote({ kind: 'error', text: e.message }));
                                        }, children: "Ask Kodi to look for new files" }))] }), k?.pendingScan && _jsxs("p", { className: "hint", style: { margin: '10px 0 0' }, children: ["The last Apply waits for Kodi (", when(k.pendingScan), ")."] }), (k?.pendingRefresh ?? 0) > 0 && _jsxs("p", { className: "hint", style: { margin: '10px 0 0' }, children: [k.pendingRefresh.toLocaleString('en-GB'), " changed items wait for Kodi to re-read them."] }), kodiNote && _jsx("div", { className: `banner banner-${kodiNote.kind}`, role: "alert", style: { marginTop: 10 }, children: kodiNote.text })] }), _jsx(WatchedPanel, { status: status, refresh: refresh }), _jsxs("section", { className: "panel", "aria-labelledby": "scores-h", children: [_jsx("div", { className: "panel-head", children: _jsx("h2", { id: "scores-h", children: "IMDb scores" }) }), _jsxs("div", { className: "actions", style: { justifyContent: 'space-between' }, children: [_jsx("span", { className: "num", children: sc?.refreshed
                                            ? `Updated ${when(sc.refreshed)} · ${sc.ratings.toLocaleString('en-GB')} scores · next ${when(sc.next)}`
                                            : 'Not downloaded yet · weekly' }), tmdb
                                        ? _jsx("button", { className: "btn btn-secondary btn-sm", type: "button", "aria-busy": starting === 'scores', onClick: () => start('scores', api.refreshScores), children: "Refresh now" })
                                        : _jsx("button", { className: "btn btn-secondary btn-sm", type: "button", "aria-disabled": "true", title: "Add the TMDB token in Settings first", children: "Refresh now" })] })] }), folderProblems.length > 0 && (_jsxs("section", { className: "panel", "aria-labelledby": "dirs-h", children: [_jsxs("div", { className: "panel-head", children: [_jsx("h2", { id: "dirs-h", children: "Folders" }), _jsx(Link, { to: "/settings", className: "small", children: "Settings" })] }), _jsx("ul", { className: "rows", children: folderProblems })] }))] })] }));
}
// Until the essentials are set up, the Dashboard says what's left; each step ticks itself and links to
// where it's done. An install that is set up never sees it.
function SetupChecklist({ status }) {
    const k = status.kodi;
    const folder = (p) => p.replace(/[/\\]+$/, '').split(/[/\\]/).pop() ?? p;
    const sources = k && k.connected ? k.sources : undefined;
    const steps = [
        { done: status.tmdb.configured, text: 'Add your TMDB token', to: '/settings' },
        { done: Boolean(k), text: 'Connect Kodi', to: '/settings' },
        { done: Boolean(sources?.tv && sources?.film), to: '/settings', pending: sources ? undefined : 'checked when Kodi answers',
            text: `Kodi has video sources for the ${folder(status.paths.tv.path)} and ${folder(status.paths.film.path)} folders` },
        { done: Boolean(status.inbox.scannedAt), text: 'Check the downloads for the first time', to: '/inbox' },
        { done: Boolean(k?.canWake), text: `Optional: let muthur wake the ${status.names.device}`, to: '/settings', optional: true },
    ];
    const needed = steps.filter((s) => !s.optional && !(s.pending && !s.done));
    if (needed.every((s) => s.done) && !(sources && !(sources.tv && sources.film)))
        return null;
    return (_jsxs("section", { className: "panel", "aria-labelledby": "setup-h", children: [_jsxs("div", { className: "panel-head", children: [_jsx("h2", { id: "setup-h", children: "Getting started" }), _jsxs("span", { className: "small muted", children: [steps.filter((s) => s.done).length, " of ", steps.length, " done"] })] }), _jsx("ul", { className: "rows", children: steps.map((s) => (_jsxs("li", { children: [_jsxs("span", { className: "status", children: [_jsx(Dot, { kind: s.done ? 'dot-success' : '' }), s.done ? s.text : _jsx(Link, { to: s.to, children: s.text })] }), !s.done && s.pending && _jsx("span", { className: "small muted", children: s.pending })] }, s.text))) })] }));
}
// What's wrong in the library, in Health's groups (DESIGN.md §1.11): a number per group and a line naming what is
// in it, each opening its own panel in Health (Duplicates its own page). Only groups with something in them.
function LibraryProblems({ status }) {
    const l = status?.library ?? {};
    const dups = status?.duplicatesAt ? status.duplicates : 0;
    const dupFilms = status?.duplicatesAt ? status.duplicateFilms ?? 0 : 0;
    const parts = (...p) => p.filter(([n]) => (n ?? 0) > 0).map(([n, one, many]) => count(n ?? 0, one, many)).join(' · ');
    const tiles = [
        ['IMDb scores', (l.imdbData ?? 0) + (l.scores ?? 0), parts([l.imdbData, 'show to download', 'shows to download'], [l.scores, 'NFO to add to', 'NFOs to add to']), '/health#scores'],
        ['Missing in Kodi', (l.nfos ?? 0) + (l.posters ?? 0) + (l.subtitles ?? 0), parts([l.nfos, 'NFO'], [l.posters, 'poster'], [l.subtitles, 'video’s subtitles', 'videos’ subtitles']), '/health#kodi'],
        ['Questions for you', l.questions ?? 0, 'muthur isn’t sure: only you can answer', '/health#questions'],
        ['Duplicates', dups, `${parts([dupFilms, 'film'], [dups - dupFilms, 'episode'])}: choose which copy to keep`, '/duplicates'],
        ['Tidy up', (l.renames ?? 0) + (l.subTiming ?? 0) + (l.kodiEntries ?? 0) + (l.leftovers ?? 0),
            parts([l.renames, 'name'], [l.subTiming, 'subtitle file out of sync', 'subtitle files out of sync'], [l.kodiEntries, 'old Kodi entry', 'old Kodi entries'], [l.leftovers, 'leftover']), '/health#tidy'],
    ];
    const shown = tiles.filter(([, n]) => n > 0);
    if (!shown.length && !l.at) {
        // Never counted (a new install, or kinds of fixes added by an update): not 'in order', just not known yet.
        return _jsxs("span", { className: "status", children: [_jsx(Dot, { kind: "dot-warning" }), "Not checked yet \u00B7 ", _jsx(Link, { to: "/health", children: "Check in Health" })] });
    }
    if (!shown.length) {
        return _jsxs("span", { className: "status", children: [_jsx(Dot, { kind: "dot-success" }), status?.duplicatesAt ? 'In order' : 'In order · duplicates not checked yet'] });
    }
    return (_jsx("div", { className: "tiles inset groups", children: shown.map(([label, n, what, to]) => (_jsxs(Link, { className: "tile", to: to, children: [_jsx("span", { className: "label", children: label }), _jsx("strong", { children: n.toLocaleString('en-GB') }), _jsx("span", { className: "sub", children: what })] }, label))) }));
}
