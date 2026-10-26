import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import { Dot, JobError, Loading } from '../components';
import { count, libraryPath, middle, size, when } from '../labels';
import { Link, navigate, useLocation } from '../nav';
const name = (p) => p.split('/').pop() ?? p;
function freed(g, keep) {
    return g.copies.filter((c) => c.path !== keep).reduce((n, c) => n + c.quality.size, 0);
}
function Group({ g, keep, plan, selected, onKeep, onSelect }) {
    const quarantined = plan.ops.filter((o) => o.op === 'quarantine');
    const renamed = plan.ops.filter((o) => o.op === 'move');
    const watched = g.copies.some((c) => c.watched);
    return (_jsxs("section", { className: "panel", style: { display: 'flex', flexDirection: 'column', gap: 10, borderColor: selected ? 'var(--mark)' : undefined }, children: [_jsxs("div", { className: "panel-head", style: { marginBottom: 0 }, children: [_jsxs("label", { className: "choice", style: { alignItems: 'center', minWidth: 0 }, children: [_jsx("input", { type: "checkbox", checked: selected, onChange: (e) => onSelect(e.target.checked) }), _jsx("h2", { style: { fontSize: '1.1rem', overflowWrap: 'anywhere' }, children: g.label })] }), _jsxs("span", { className: "small muted", children: [g.show && _jsx(Link, { to: `/library?${new URLSearchParams({ folder: g.show })}`, children: g.show }), g.note ? ` · ${g.note}` : '', watched ? ' · watched' : ''] })] }), _jsxs("fieldset", { style: { border: 0, padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 6 }, children: [_jsx("legend", { className: "small muted", style: { marginBottom: 4 }, children: "Which copy stays?" }), g.copies.map((c) => (_jsxs("label", { className: "choice", style: { minWidth: 0, overflowWrap: 'anywhere', padding: '6px 8px', borderRadius: 'var(--radius-sm)', background: c.path === keep ? 'var(--surface-muted)' : undefined }, children: [_jsx("input", { type: "radio", name: `keep-${g.id}`, checked: c.path === keep, onChange: () => onKeep(c.path) }), _jsxs("span", { style: { display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }, children: [_jsxs("span", { className: "small", children: [_jsx("strong", { children: c.label }), " \u00B7 ", size(c.quality.size), c.nfo ? ' · has NFO' : '', c.watched ? ' · watched' : '', c.path === g.keep && _jsx("span", { className: "muted", children: " \u00B7 muthur\u2019s pick" })] }), _jsx("span", { className: "mono small muted", title: libraryPath(c.path), style: { wordBreak: 'break-all' }, children: middle(libraryPath(c.path), 110) })] })] }, c.path)))] }), _jsxs("div", { className: "small", style: { display: 'flex', flexDirection: 'column', gap: 2, overflowWrap: 'anywhere', minWidth: 0 }, children: [_jsxs("span", { children: ["Stays as ", _jsx("span", { className: "mono", style: { color: 'var(--accent-text)', wordBreak: 'break-all' }, children: libraryPath(plan.final) })] }), _jsxs("span", { className: "muted", children: ["To quarantine: ", quarantined.length, " ", quarantined.length === 1 ? 'file' : 'files', " (", size(freed(g, keep)), ")", renamed.length > 0 ? ` · renamed: ${renamed.map((o) => name(o.src)).slice(0, 3).join(', ')}${renamed.length > 3 ? '…' : ''}` : ''] })] })] }));
}
export function DuplicatesPage({ status, refresh }) {
    const { search } = useLocation();
    const kind = (new URLSearchParams(search).get('show') ?? 'all');
    const [data, setData] = useState(null);
    const [keep, setKeep] = useState({});
    const [plans, setPlans] = useState({});
    const [selected, setSelected] = useState(new Set());
    const [asking, setAsking] = useState(false);
    const [last, setLast] = useState(null);
    const [error, setError] = useState(null);
    const running = Boolean(status?.job?.running);
    useEffect(() => {
        api.duplicates().then((d) => { setData(d); setSelected(new Set()); setKeep({}); setPlans({}); }).catch((e) => setError(e.message));
        api.duplicatesLast().then((r) => setLast('items' in r ? r : null)).catch(() => undefined);
    }, [running, status?.job?.finished]);
    const groups = useMemo(() => (data?.groups ?? []).filter((g) => kind === 'all' || g.kind === kind), [data, kind]);
    const keepOf = (g) => keep[g.id] ?? g.keep;
    const planOf = (g) => plans[g.id] ?? g.plan;
    const chosen = (data?.groups ?? []).filter((g) => selected.has(g.id));
    const files = chosen.reduce((n, g) => n + planOf(g).ops.filter((o) => o.op === 'quarantine').length, 0);
    const bytes = chosen.reduce((n, g) => n + freed(g, keepOf(g)), 0);
    const changeKeep = (g, path) => {
        setKeep((k) => ({ ...k, [g.id]: path }));
        api.duplicatePlan(g.id, path).then((p) => setPlans((x) => ({ ...x, [g.id]: p }))).catch((e) => setError(e.message));
    };
    const select = (id, on) => setSelected((s) => { const n = new Set(s); if (on)
        n.add(id);
    else
        n.delete(id); return n; });
    const apply = () => {
        setAsking(false);
        setError(null);
        begin('apply', () => api.applyDuplicates(chosen.map((g) => ({ id: g.id, keep: keepOf(g) }))));
    };
    // The button pressed spins until its request is answered; a job then shows in the job bar (DESIGN.md §7.6).
    const [starting, setStarting] = useState(null);
    const begin = (key, request) => {
        setStarting(key);
        setError(null);
        request().then(refresh).catch((e) => setError(e.message)).finally(() => setStarting(null));
    };
    const check = () => begin('check', api.scanDuplicates);
    return (_jsxs("div", { className: "page", children: [_jsxs("header", { className: "page-head", children: [_jsxs("div", { children: [_jsx("p", { className: "eyebrow", children: "More than one copy" }), _jsx("h1", { children: "Duplicates" }), _jsx("p", { className: "lede", children: data?.at ? `${count(data.groups.length, 'episode or film has', 'episodes and films have')} more than one copy · checked ${when(data.at)}`
                                    : 'Not checked yet. Look for duplicates to compare the copies in your library.' })] }), _jsxs("div", { className: "actions", children: [!asking && !data?.groups.length && (_jsx("button", { className: "btn btn-primary", type: "button", "aria-busy": starting === 'check', onClick: check, children: data?.at ? 'Check again' : 'Look for duplicates' })), !asking && Boolean(data?.groups.length) && _jsx("button", { className: "btn btn-secondary btn-sm", type: "button", "aria-busy": starting === 'check', onClick: check, children: "Check again" }), !asking && Boolean(data?.groups.length) && (chosen.length > 0
                                ? _jsxs("button", { className: "btn btn-primary", type: "button", disabled: running, onClick: () => setAsking(true), children: ["Resolve ", chosen.length, " selected"] })
                                : _jsx("button", { className: "btn btn-primary", type: "button", "aria-disabled": "true", title: "Select groups first", children: "Resolve selected" }))] })] }), asking && (_jsxs("section", { className: "panel", role: "group", "aria-labelledby": "ask-h", style: { display: 'flex', flexDirection: 'column', gap: 12, borderColor: 'var(--danger-text)' }, children: [_jsxs("h2", { id: "ask-h", style: { margin: 0, fontSize: '1.15rem', fontWeight: 650 }, children: ["Move ", files, " ", files === 1 ? 'file' : 'files', " (", size(bytes), ") to quarantine and keep one copy of ", chosen.length, " ", chosen.length === 1 ? 'item' : 'items', "?"] }), _jsx("p", { className: "hint", children: "The copy that stays takes over the library name, NFO and artwork where that\u2019s another copy\u2019s. Kodi then scans those folders and the copy that stays gets the highest play count and resume point of all copies; their old entries are removed. muthur takes a fresh watched backup first. Everything can be put back from History." }), _jsxs("div", { className: "actions", style: { justifyContent: 'flex-end' }, children: [_jsx("button", { className: "btn btn-secondary", type: "button", autoFocus: true, onClick: () => setAsking(false), children: "Cancel" }), _jsx("button", { className: "btn btn-danger", type: "button", onClick: apply, children: "Move to quarantine" })] })] })), _jsx(JobError, { job: status?.job }), !data && !error && _jsx(Loading, { label: "Loading the duplicates" }), error && _jsx("div", { className: "banner banner-error", role: "alert", children: error }), last && !running && status?.job?.name === 'duplicates-apply' && (_jsxs("div", { className: `banner ${last.stopped ? 'banner-warn' : 'banner-note'}`, role: "status", style: { flexDirection: 'column', alignItems: 'stretch' }, children: [_jsxs("span", { className: "status", children: [_jsx(Dot, { kind: last.stopped ? 'dot-warning' : 'dot-success' }), last.applied, " resolved", last.stopped ? `, ${last.stopped} stopped` : '', ". What moved is in History."] }), last.items.filter((i) => !i.ok || (i.kodi && !i.kodi.ok)).map((i) => (_jsxs("span", { className: "small", children: [i.label, ": ", i.why ?? i.kodi?.why] }, i.id)))] })), data?.at && (_jsxs("div", { className: "inline", style: { justifyContent: 'space-between' }, children: [_jsx("div", { className: "seg filters", role: "group", "aria-label": "Show", children: [['all', 'All'], ['episode', 'Episodes'], ['film', 'Films']].map(([k, label]) => (_jsxs("button", { type: "button", "aria-pressed": kind === k, onClick: () => navigate(k === 'all' ? '/duplicates' : `/duplicates?show=${k}`), children: [label, " ", _jsx("span", { className: "num muted", children: (data.groups ?? []).filter((g) => k === 'all' || g.kind === k).length })] }, k))) }), groups.length > 0 && (_jsxs("label", { className: "choice small", children: [_jsx("input", { type: "checkbox", checked: groups.every((g) => selected.has(g.id)), onChange: (e) => setSelected((s) => { const n = new Set(s); groups.forEach((g) => (e.target.checked ? n.add(g.id) : n.delete(g.id))); return n; }) }), _jsxs("span", { children: ["Select all ", groups.length, " shown, with muthur\u2019s picks"] })] }))] })), data?.at && groups.length === 0 && (_jsxs("section", { className: "panel", style: { textAlign: 'center', padding: '40px 16px' }, children: [_jsx("h2", { style: { margin: '0 0 6px', fontSize: '1.2rem' }, children: "No duplicates" }), _jsx("p", { className: "hint", children: "Every episode and film has one copy." })] })), groups.map((g) => (_jsx(Group, { g: g, keep: keepOf(g), plan: planOf(g), selected: selected.has(g.id), onKeep: (p) => changeKeep(g, p), onSelect: (on) => select(g.id, on) }, g.id)))] }));
}
