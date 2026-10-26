import { Fragment as _Fragment, jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import { Dot, JobError, Loading } from '../components';
import { SIGNALS, STATUS, libraryPath, middle, size, splitId, when } from '../labels';
import { Link, navigate, useLocation } from '../nav';
const FILTERS = [['all', 'All'], ['ready', 'Ready'], ['review', 'Needs you'], ['suspicious', 'Suspicious'], ['packed', 'Packed'], ['waiting', 'Still downloading'], ['ignored', 'Ignored']];
function Detail({ item, onChanged }) {
    const [busy, setBusy] = useState(false);
    const toQuarantine = () => {
        setBusy(true);
        api.quarantineDownload(item.id)
            .then(() => onChanged('Moved to quarantine. It can be put back from History, and is deleted for good only when you empty that day.'))
            .catch((e) => onChanged(null, e.message))
            .finally(() => setBusy(false));
    };
    const s = STATUS[item.status] ?? { label: item.status, dot: '' };
    const placed = item.files.filter((f) => f.target);
    return (_jsxs("aside", { className: "panel narrow", "aria-label": "What would happen", style: { display: 'flex', flexDirection: 'column', gap: 16 }, children: [_jsxs("div", { children: [_jsx("p", { className: "eyebrow", children: s.label }), item.title
                        ? _jsxs("h2", { style: { margin: '2px 0 0', fontSize: '1.3rem', fontWeight: 650, overflowWrap: 'anywhere' }, children: [item.title, item.year ? ` (${item.year})` : ''] })
                        : _jsx("h2", { className: "mono", style: { margin: '2px 0 0', fontSize: '0.95rem', fontWeight: 600, overflowWrap: 'anywhere' }, children: splitId(item.id).name }), "  ", _jsx("p", { className: "hint", style: { marginTop: 4 }, children: item.reason })] }), placed.length > 0 && (_jsx("div", { style: { display: 'flex', flexDirection: 'column', gap: 10 }, children: placed.map((f) => (_jsxs("div", { style: { display: 'flex', flexDirection: 'column', gap: 2 }, children: [_jsx("span", { className: "mono small muted", style: { wordBreak: 'break-all' }, children: f.source }), _jsxs("span", { className: "mono small", style: { wordBreak: 'break-all', color: 'var(--accent-text)' }, children: ["\u2192 ", f.library, "/", f.target] }), f.writes.length > 0 && _jsxs("span", { className: "small muted", children: ["Written next to it: ", f.writes.join(', ')] })] }, f.source))) })), item.notes.map((n) => _jsx("p", { className: "hint", children: n }, n)), item.status === 'review' && item.candidates.length > 0 && (_jsxs("div", { children: [_jsx("h3", { style: { margin: '0 0 6px', fontSize: '1rem', fontWeight: 650 }, children: "What it could be" }), _jsx("ul", { className: "rows", children: item.candidates.map((c) => (_jsxs("li", { style: { flexDirection: 'column', alignItems: 'flex-start' }, children: [_jsxs("span", { children: [_jsx("strong", { children: c.title }), c.year ? ` (${c.year})` : '', c.originalTitle && c.originalTitle !== c.title ? _jsxs("span", { className: "muted", children: [" \u00B7 ", c.originalTitle] }) : null] }), _jsx("span", { className: "small muted", children: Object.entries(c.signals).filter(([k]) => k !== 'popularity').map(([k, v]) => `${SIGNALS[k] ?? k} ${Math.round(v * 100)}%`).join(' · ') })] }, c.tmdbId))) })] })), item.status === 'review' && _jsx(Link, { to: "/review", className: "btn btn-secondary btn-sm", style: { alignSelf: 'flex-start' }, children: "Choose in Review" }), (item.status === 'suspicious' || item.status === 'packed') && (_jsx("button", { className: "btn btn-secondary btn-sm", type: "button", disabled: busy, "aria-busy": busy, style: { alignSelf: 'flex-start' }, onClick: toQuarantine, children: "Move to quarantine" })), _jsx("span", { className: "small muted", children: size(item.size) })] }));
}
export function InboxPage({ status, refresh }) {
    const { search } = useLocation();
    const filter = (new URLSearchParams(search).get('show') ?? 'all');
    const [data, setData] = useState(null);
    const [selected, setSelected] = useState(null);
    const [message, setMessage] = useState(null);
    const [note, setNote] = useState(null);
    const running = Boolean(status?.job?.running);
    useEffect(() => {
        api.inbox().then(setData).catch((e) => setMessage(e.message));
    }, [status?.inbox.scannedAt, running]);
    const items = useMemo(() => (data?.items ?? []).filter((i) => filter === 'all' || i.status === filter), [data, filter]);
    const current = items.find((i) => i.id === selected) ?? items[0] ?? null;
    const count = (k) => (k === 'all' ? data?.items.length : data?.items.filter((i) => i.status === k).length) ?? 0;
    const [starting, setStarting] = useState(null);
    const begin = (key, request) => {
        setStarting(key);
        setMessage(null);
        request().then(refresh).catch((e) => setMessage(e.message)).finally(() => setStarting(null));
    };
    const scan = () => begin('scan', api.scan);
    // A standing reason stays reachable: aria-disabled with the reason as its title, not a mute 'disabled' (DESIGN.md §3).
    const noTmdb = !status?.tmdb.configured;
    const needsTmdb = noTmdb ? { 'aria-disabled': true, title: 'Add the TMDB token in Settings first' } : {};
    const ready = (data?.items ?? []).filter((i) => i.status === 'ready');
    const [asking, setAsking] = useState(false);
    const toTv = ready.filter((i) => i.kind === 'tv').reduce((n, i) => n + i.files.filter((f) => f.target).length, 0);
    const toFilm = ready.filter((i) => i.kind === 'movie').length;
    const newShows = new Set(ready.filter((i) => i.kind === 'tv' && !i.known).map((i) => i.files[0]?.target?.split('/')[0])).size;
    const apply = () => {
        setAsking(false);
        begin('apply', () => api.apply());
    };
    return (_jsxs("div", { className: "page", children: [_jsxs("header", { className: "page-head", children: [_jsxs("div", { children: [_jsx("p", { className: "eyebrow", children: "Finished downloads" }), _jsx("h1", { children: "Inbox" }), _jsxs("p", { className: "lede", children: [status && _jsxs(_Fragment, { children: [_jsx("span", { className: "mono small", style: { overflowWrap: 'anywhere' }, children: libraryPath(status.paths.downloads.path) }), " \u00B7 "] }), "checked ", when(data?.scannedAt ?? null)] })] }), _jsx("div", { className: "actions", children: asking ? null : ready.length > 0 ? (_jsxs(_Fragment, { children: [_jsx("button", { className: "btn btn-secondary btn-sm", type: "button", ...needsTmdb, "aria-busy": starting === 'scan', onClick: noTmdb ? undefined : scan, children: "Look again" }), _jsxs("button", { className: "btn btn-primary", type: "button", "aria-busy": starting === 'apply', onClick: () => setAsking(true), children: ["Apply ", ready.length, " ready ", ready.length === 1 ? 'item' : 'items'] })] })) : (_jsx("button", { className: "btn btn-primary", type: "button", ...needsTmdb, "aria-busy": starting === 'scan', onClick: noTmdb ? undefined : scan, children: "Look for new downloads" })) })] }), asking && (_jsxs("section", { className: "panel", role: "group", "aria-labelledby": "ask-h", style: { display: 'flex', flexDirection: 'column', gap: 12, borderColor: 'var(--mark)' }, children: [_jsxs("h2", { id: "ask-h", style: { margin: 0, fontSize: '1.15rem', fontWeight: 650 }, children: ["Move ", ready.length, " ", ready.length === 1 ? 'download' : 'downloads', " into your library?"] }), _jsxs("ul", { className: "rows", children: [toTv > 0 && _jsxs("li", { children: [_jsx("span", { children: "Episodes into TV" }), _jsxs("span", { className: "num", children: [toTv, newShows > 0 ? ` · ${newShows} new show folder${newShows === 1 ? '' : 's'}` : ''] })] }), toFilm > 0 && _jsxs("li", { children: [_jsx("span", { children: "Films into Film" }), _jsx("span", { className: "num", children: toFilm })] }), _jsxs("li", { children: [_jsx("span", { children: "Written next to them" }), _jsx("span", { children: "NFO files and artwork, only where none exist" })] }), _jsxs("li", { children: [_jsx("span", { children: "What\u2019s left of each download" }), _jsx("span", { children: "to quarantine, if it holds no video" })] })] }), _jsx("p", { className: "hint", children: "Nothing is overwritten; History can put it back." }), _jsxs("div", { className: "actions", style: { justifyContent: 'flex-end' }, children: [_jsx("button", { className: "btn btn-secondary", type: "button", autoFocus: true, onClick: () => setAsking(false), children: "Cancel" }), _jsx("button", { className: "btn btn-primary", type: "button", onClick: apply, children: "Move them" })] })] })), message && _jsx("div", { className: "banner banner-error", role: "alert", children: message }), note && _jsx("div", { className: "banner banner-note", role: "status", children: note }), _jsx(JobError, { job: status?.job }), !data && !message && _jsx(Loading, { label: "Loading the downloads" }), status?.job && !status.job.running && status.job.name === 'apply' && !status.job.error && (_jsxs("div", { className: "banner banner-note", role: "status", children: [_jsxs("span", { className: "status", children: [_jsx(Dot, { kind: "dot-success" }), "Done. What moved, and the way to put it back, is in History."] }), _jsx(Link, { to: "/history", children: "Open History" })] })), _jsx("div", { className: "seg filters", role: "group", "aria-label": "Show", children: FILTERS.map(([k, label]) => (_jsxs("button", { type: "button", "aria-pressed": filter === k, onClick: () => navigate(k === 'all' ? '/inbox' : `/inbox?show=${k}`), children: [label, " ", _jsx("span", { className: "num muted", children: count(k) })] }, k))) }), data && data.items.length === 0 && !running ? (_jsxs("section", { className: "panel", style: { textAlign: 'center', padding: '40px 16px' }, children: [_jsx("h2", { style: { margin: '0 0 6px', fontSize: '1.2rem' }, children: data.scannedAt ? 'Nothing waiting' : 'Not checked yet' }), _jsx("p", { className: "hint", children: data.scannedAt ? 'Nothing finished yet.' : 'Check the downloads to see what’s there.' })] })) : (_jsxs("div", { className: "split", children: [_jsxs("section", { className: "panel wide", "aria-label": "Downloads", style: { padding: '10px 14px' }, children: [_jsxs("div", { className: "list-head", children: [_jsx("span", { children: "Download" }), _jsx("span", { children: "Would become" }), _jsx("span", { children: "Status" })] }), items.map((i) => {
                                const s = STATUS[i.status] ?? { label: i.status, dot: '' };
                                return (_jsxs("button", { type: "button", className: "list-row", "aria-pressed": current?.id === i.id, onClick: () => setSelected(i.id), children: [_jsxs("span", { style: { display: 'flex', flexDirection: 'column', minWidth: 0 }, title: i.id, children: [_jsx("span", { className: "mono small", children: middle(splitId(i.id).name, 46) }), splitId(i.id).folder && _jsxs("span", { className: "small muted", children: ["in ", splitId(i.id).folder] })] }), _jsxs("span", { style: { display: 'flex', flexDirection: 'column', minWidth: 0 }, children: [i.title && _jsxs("span", { className: "ellipsis", style: { fontWeight: 600 }, children: [i.title, i.year ? ` (${i.year})` : ''] }), _jsx("span", { className: i.title ? 'small muted ellipsis' : 'small ellipsis', children: i.reason })] }), _jsxs("span", { className: "status small", children: [_jsx(Dot, { kind: s.dot }), s.label] })] }, i.id));
                            }), items.length === 0 && _jsx("p", { className: "hint", style: { padding: 12 }, children: "Nothing in this group." })] }), current && _jsx(Detail, { item: current, onChanged: (text, error) => {
                            setNote(text);
                            setMessage(error ?? null);
                            if (text) {
                                api.inbox().then(setData).catch(() => undefined);
                                refresh(); // the counters, tabs and Dashboard banner come from the status, not the list
                            }
                        } })] }))] }));
}
