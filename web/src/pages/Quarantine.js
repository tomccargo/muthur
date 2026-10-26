import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useState } from 'react';
import { api } from '../api';
import { count, libraryPath, size } from '../labels';
// The quarantine, per day. Emptying deletes for good, so it only happens on the reader's confirmation (DESIGN.md §7.3).
export function QuarantinePanel({ busy }) {
    const [days, setDays] = useState(null);
    const [chosen, setChosen] = useState(new Set());
    const [asking, setAsking] = useState(false);
    const [message, setMessage] = useState(null);
    const [open, setOpen] = useState(null);
    const [notes, setNotes] = useState([]);
    const show = (day) => {
        if (open === day) {
            setOpen(null);
            return;
        }
        api.quarantineDay(day).then((r) => { setNotes(r.notes); setOpen(day); }).catch((e) => setMessage({ kind: 'error', text: e.message }));
    };
    const load = () => api.quarantine().then((q) => { setDays(q.days); setChosen(new Set()); }).catch((e) => setMessage({ kind: 'error', text: e.message }));
    useEffect(() => { load(); }, [busy]); // eslint-disable-line react-hooks/exhaustive-deps
    const picked = (days ?? []).filter((d) => chosen.has(d.day));
    const files = picked.reduce((n, d) => n + d.files, 0);
    const bytes = picked.reduce((n, d) => n + d.size, 0);
    const empty = () => {
        setAsking(false);
        api.emptyQuarantine(picked.map((d) => d.day))
            .then((r) => { setMessage({ kind: 'note', text: `Deleted ${size(r.freed)} for good.` }); load(); })
            .catch((e) => setMessage({ kind: 'error', text: e.message }));
    };
    return (_jsxs("section", { className: "panel", "aria-labelledby": "q-h", style: { display: 'flex', flexDirection: 'column', gap: 10 }, children: [_jsxs("div", { className: "panel-head", style: { marginBottom: 0 }, children: [_jsx("h2", { id: "q-h", children: "Quarantine" }), _jsx("span", { className: "small muted", children: days ? `${count((days ?? []).reduce((n, d) => n + d.files, 0), 'file')} · ${size((days ?? []).reduce((n, d) => n + d.size, 0) || 1)}` : '' })] }), days && days.length === 0 && _jsx("p", { className: "hint", children: "Empty." }), days && days.length > 0 && (_jsx("ul", { className: "rows", children: days.map((d) => (_jsxs("li", { style: { flexDirection: 'column', gap: 4 }, children: [_jsxs("span", { style: { display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }, children: [_jsxs("label", { className: "choice", children: [_jsx("input", { type: "checkbox", checked: chosen.has(d.day), onChange: (e) => setChosen((s) => { const n = new Set(s); if (e.target.checked)
                                                n.add(d.day);
                                            else
                                                n.delete(d.day); return n; }) }), _jsx("span", { children: new Date(d.day).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }) })] }), _jsxs("span", { className: "small num", children: [count(d.files, 'file'), " \u00B7 ", size(d.size || 1), " \u00B7 ", _jsx("button", { type: "button", className: "btn-link small", onClick: () => show(d.day), children: open === d.day ? 'Hide' : 'What and why' })] })] }), open === d.day && (notes.length ? (_jsx("ul", { className: "rows", style: { paddingLeft: 26 }, children: notes.map((n, i) => (_jsxs("li", { style: { flexDirection: 'column', gap: 2 }, children: [_jsx("span", { className: "mono small", style: { wordBreak: 'break-all' }, children: libraryPath(n.from) }), _jsx("span", { className: "small muted", children: n.why })] }, i))) })) : _jsx("p", { className: "hint", style: { paddingLeft: 26 }, children: "No notes for this day; it was filled before muthur kept them." }))] }, d.day))) })), asking && (_jsxs("div", { className: "banner banner-error", role: "group", "aria-label": "Empty quarantine", style: { flexDirection: 'column', alignItems: 'stretch' }, children: [_jsxs("strong", { children: ["Delete ", files, " ", files === 1 ? 'file' : 'files', " (", size(bytes || 1), ") for good?"] }), _jsx("span", { children: "This can\u2019t be undone, and History can no longer put these files back." }), _jsxs("div", { className: "actions", style: { justifyContent: 'flex-end' }, children: [_jsx("button", { className: "btn btn-secondary btn-sm", type: "button", autoFocus: true, onClick: () => setAsking(false), children: "Cancel" }), _jsx("button", { className: "btn btn-danger btn-sm", type: "button", onClick: empty, children: "Delete for good" })] })] })), message && _jsx("div", { className: `banner banner-${message.kind}`, role: "status", children: message.text }), !asking && picked.length > 0 && (_jsx("div", { className: "actions", children: _jsxs("button", { className: "btn btn-danger-outline btn-sm", type: "button", disabled: busy, "aria-busy": busy, onClick: () => setAsking(true), children: ["Empty ", picked.length, " ", picked.length === 1 ? 'day' : 'days', "\u2026"] }) }))] }));
}
