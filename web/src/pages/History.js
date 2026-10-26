import { Fragment as _Fragment, jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useState } from 'react';
import { api } from '../api';
import { Dot, JobError, Loading } from '../components';
import { count, libraryPath, middle, size, splitId, when } from '../labels';
const VERB = { move: 'Moved', write: 'Wrote', quarantine: 'Quarantined', mkdir: 'Made folder', update: 'New scores in' };
function Ops({ run }) {
    const [ops, setOps] = useState(null);
    useEffect(() => { api.run(run.id).then((r) => setOps(r.ops)).catch(() => setOps([])); }, [run.id, run.undone]);
    if (!ops)
        return _jsx("p", { className: "hint", children: "Loading\u2026" });
    const shown = ops.filter((o) => o.op !== 'mkdir');
    return (_jsx("ul", { className: "rows", style: { marginTop: 8 }, children: shown.map((o) => (_jsxs("li", { style: { flexDirection: 'column', gap: 2 }, children: [_jsxs("span", { className: "status small", children: [_jsx(Dot, { kind: o.status === 'done' ? (o.op === 'quarantine' ? 'dot-warning' : 'dot-success') : '' }), o.status === 'undone' ? `${VERB[o.op]}, then put back` : o.status === 'failed' ? `${VERB[o.op]}: didn’t happen` : VERB[o.op], o.size ? _jsxs("span", { className: "muted", children: ["\u00B7 ", size(o.size)] }) : null] }), o.src && o.op !== 'update' && _jsx("span", { className: "mono small muted", style: { wordBreak: 'break-all' }, children: libraryPath(o.src) }), _jsxs("span", { className: "mono small", style: { wordBreak: 'break-all', textDecoration: o.status === 'undone' ? 'line-through' : undefined }, children: [o.src && o.op !== 'update' ? '→ ' : '', libraryPath(o.dst)] }), o.error && _jsxs("span", { className: "small", style: { color: 'var(--warn-text)' }, children: ["Not put back: ", o.error] })] }, o.id))) }));
}
function RunCard({ run, busy, onUndo }) {
    const [open, setOpen] = useState(false);
    const [asking, setAsking] = useState(false);
    const s = run.summary;
    const stopped = [...(s?.items ?? []).filter((i) => !i.ok), ...(s?.failed ?? []).map((f) => ({ id: f.path, ok: false, why: f.why }))];
    const fixed = Object.values(s?.done ?? {}).reduce((n, v) => n + v, 0);
    return (_jsxs("section", { className: "panel", style: { display: 'flex', flexDirection: 'column', gap: 10 }, children: [_jsxs("div", { className: "panel-head", style: { marginBottom: 0 }, children: [_jsx("h2", { children: new Date(run.started * 1000).toDateString() === new Date().toDateString() ? `Today, ${when(run.started)}` : when(run.started) }), _jsx("span", { className: "status small", children: run.undone ? _jsxs(_Fragment, { children: [_jsx(Dot, {}), "Put back ", when(run.undone)] })
                            : s?.interrupted ? _jsxs(_Fragment, { children: [_jsx(Dot, { kind: "dot-warning" }), "Stopped by a restart \u00B7 what it changed stays"] })
                                : run.kind === 'scores' ? _jsxs(_Fragment, { children: [_jsx(Dot, { kind: "dot-success" }), "IMDb scores"] })
                                    : run.kind === 'library' ? _jsxs(_Fragment, { children: [_jsx(Dot, { kind: "dot-success" }), "Library edit"] })
                                        : run.kind === 'health' ? _jsxs(_Fragment, { children: [_jsx(Dot, { kind: "dot-success" }), count(fixed, 'fix', 'fixes'), stopped.length ? `, ${stopped.length} not done` : ''] })
                                            : _jsxs(_Fragment, { children: [_jsx(Dot, { kind: "dot-success" }), s?.applied ?? 0, " applied", stopped.length ? `, ${stopped.length} stopped` : ''] }) })] }), _jsx("p", { className: "hint", style: { margin: 0 }, children: run.kind === 'library'
                    ? `${s?.label ?? 'A library edit'} · ${run.counts.update + run.counts.write} file${run.counts.update + run.counts.write === 1 ? '' : 's'} written; the old ones are kept for putting back`
                    : run.kind === 'scores'
                        ? `${run.counts.update} NFO${run.counts.update === 1 ? '' : 's'} got new IMDb scores; the old files are kept for putting back`
                        : `${run.counts.move} file${run.counts.move === 1 ? '' : 's'} moved · ${run.counts.write} written · ${run.counts.quarantine} to quarantine` }), stopped.length > 0 && (_jsx("ul", { className: "rows", children: stopped.map((i) => (_jsxs("li", { style: { flexDirection: 'column', gap: 2 }, children: [_jsx("span", { className: "mono small", children: middle(splitId(i.id).name, 60) }), _jsx("span", { className: "small", style: { color: 'var(--warn-text)' }, children: i.why })] }, i.id))) })), asking && (_jsxs("div", { className: "banner banner-warn", role: "group", "aria-label": "Put this run back", style: { flexDirection: 'column', alignItems: 'stretch' }, children: [_jsx("strong", { children: "Put everything from this run back?" }), _jsx("span", { children: run.kind === 'scores'
                            ? `The ${run.counts.update} NFO${run.counts.update === 1 ? '' : 's'} get their earlier scores back. A file changed since then is left alone and listed.`
                            : run.kind === 'health'
                                ? `The ${run.counts.quarantine} quarantined file${run.counts.quarantine === 1 ? '' : 's'} come back, the ${run.counts.write} file${run.counts.write === 1 ? '' : 's'} muthur wrote are removed and ${run.counts.update} NFO${run.counts.update === 1 ? '' : 's'} get their old content. A file changed since then is left alone and listed.`
                                : run.kind === 'duplicates'
                                    ? `The ${run.counts.quarantine} quarantined file${run.counts.quarantine === 1 ? '' : 's'} come back and the ${run.counts.move} renamed one${run.counts.move === 1 ? '' : 's'} get their old names. Kodi sees it after its next scan. A file changed since then is left alone and listed.`
                                    : `The ${run.counts.move} moved file${run.counts.move === 1 ? '' : 's'} go back to the downloads folder, the ${run.counts.write} file${run.counts.write === 1 ? '' : 's'} muthur wrote are removed, and quarantined leftovers return. A file changed since then is left alone and listed.` }), _jsxs("div", { className: "actions", style: { justifyContent: 'flex-end' }, children: [_jsx("button", { className: "btn btn-secondary btn-sm", type: "button", autoFocus: true, onClick: () => setAsking(false), children: "Cancel" }), _jsx("button", { className: "btn btn-danger btn-sm", type: "button", onClick: () => { setAsking(false); onUndo(); }, children: "Put it back" })] })] })), _jsxs("div", { className: "actions", children: [_jsx("button", { className: "btn btn-secondary btn-sm", type: "button", "aria-expanded": open, onClick: () => setOpen(!open), children: open ? 'Hide the changes' : 'Show the changes' }), !run.undone && !asking && (_jsx("button", { className: "btn btn-danger-outline btn-sm", type: "button", disabled: busy, "aria-busy": busy, onClick: () => setAsking(true), children: "Put this run back\u2026" }))] }), open && _jsx(Ops, { run: run })] }));
}
export function HistoryPage({ status, refresh }) {
    const [runs, setRuns] = useState(null);
    const [message, setMessage] = useState(null);
    const running = Boolean(status?.job?.running);
    useEffect(() => {
        api.history().then((h) => setRuns(h.runs)).catch((e) => setMessage(e.message));
    }, [running, status?.inbox.scannedAt]);
    const undo = (id) => {
        setMessage(null);
        api.undo(id).then(refresh).catch((e) => setMessage(e.message));
    };
    return (_jsxs("div", { className: "page", children: [_jsx("header", { className: "page-head", children: _jsxs("div", { children: [_jsx("p", { className: "eyebrow", children: "What muthur did" }), _jsx("h1", { children: "History" }), _jsx("p", { className: "lede", children: "Every run and every file it touched. A run can be put back as a whole." })] }) }), message && _jsx("div", { className: "banner banner-error", role: "alert", children: message }), _jsx(JobError, { job: status?.job }), !runs && !message && _jsx(Loading, { label: "Loading what muthur did" }), runs && runs.length === 0 && (_jsxs("section", { className: "panel", style: { textAlign: 'center', padding: '40px 16px' }, children: [_jsx("h2", { style: { margin: '0 0 6px', fontSize: '1.2rem' }, children: "Nothing yet" }), _jsx("p", { className: "hint", children: "When downloads are applied from the Inbox, each run shows up here." })] })), runs?.map((r) => _jsx(RunCard, { run: r, busy: running, onUndo: () => undo(r.id) }, r.id))] }));
}
