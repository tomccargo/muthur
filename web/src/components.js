import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
// Small pieces shared by the pages.
import { useEffect, useRef, useState } from 'react';
import { JOBS } from './labels';
export function Dot({ kind = '' }) {
    return _jsx("span", { className: `dot ${kind}`, "aria-hidden": "true" });
}
// A job that stopped with a problem, said on the page where it matters. A running job never takes room on the
// page: it is the bar along the top and the line in the rail (DESIGN.md §7.6).
export function JobError({ job }) {
    if (!job || job.running || !job.error)
        return null;
    return _jsxs("div", { className: "banner banner-error", role: "alert", children: [JOBS[job.name] ?? job.name, " stopped with a problem: ", job.error] });
}
// True once `active` has lasted `delay` ms, and then for at least `least` ms: a short job never flashes.
function useLingering(active, delay = 400, least = 600) {
    const [shown, setShown] = useState(false);
    const since = useRef(0);
    useEffect(() => {
        if (active && !shown) {
            const t = window.setTimeout(() => { since.current = Date.now(); setShown(true); }, delay);
            return () => window.clearTimeout(t);
        }
        if (!active && shown) {
            const t = window.setTimeout(() => setShown(false), Math.max(0, least - (Date.now() - since.current)));
            return () => window.clearTimeout(t);
        }
        return undefined;
    }, [active, shown, delay, least]);
    return shown;
}
// The running job as a thin bar pinned to the top of the window, over the page: it moves nothing when it comes or goes.
export function JobBar({ job }) {
    const shown = useLingering(Boolean(job?.running));
    const pct = job?.running && job.total ? Math.round((job.done / job.total) * 100) : job?.running ? 0 : 100;
    return (_jsx("div", { className: `job-bar${shown ? ' on' : ''}`, "aria-hidden": "true", children: job?.running && !job.total ? _jsx("span", { className: "fill indeterminate" }) : _jsx("span", { className: "fill", style: { width: `${pct}%` } }) }));
}
// Set-up instructions: read once, so they stay folded until asked for (DESIGN.md §1.11).
export function HowTo({ children }) {
    return _jsxs("details", { className: "howto", children: [_jsx("summary", { className: "small", children: "How to set this up" }), _jsx("p", { className: "hint", children: children })] });
}
// ---- Waiting, the same everywhere (DESIGN.md §7.6) ---------------------------------------------------
// A small ring inside the button that was pressed, while its request runs.
export function Spinner() {
    return _jsx("span", { className: "spinner", "aria-hidden": "true" });
}
// One action at a time per section: the button pressed shows the spinner (busy = its key), the others wait,
// and the result or error stays in the section until the next action. busy always clears, also on errors.
export function useAction() {
    const [busy, setBusy] = useState(null);
    const [result, setResult] = useState(null);
    const running = useRef(false);
    const run = (key, request, done) => {
        if (running.current)
            return; // a second click while the first runs does nothing
        running.current = true;
        setBusy(key);
        setResult(null);
        request()
            .then((r) => { const text = done?.(r); if (text)
            setResult({ kind: 'note', text, key }); })
            .catch((e) => setResult({ kind: 'error', text: e.message, key }))
            .finally(() => { running.current = false; setBusy(null); });
    };
    return { busy, result, run, clear: () => setResult(null) };
}
// The result of a section's action, where the action was taken.
export function ActionResult({ result }) {
    if (!result)
        return null;
    return _jsx("div", { className: `banner banner-${result.kind}`, role: result.kind === 'error' ? 'alert' : 'status', children: result.text });
}
// Seconds since a wait began, shown once it takes longer than 3 s ('Waking the Shield… 12 s').
export function useElapsed(active) {
    const [seconds, setSeconds] = useState(0);
    useEffect(() => {
        if (!active) {
            setSeconds(0);
            return;
        }
        const t0 = Date.now();
        const id = window.setInterval(() => setSeconds(Math.round((Date.now() - t0) / 1000)), 1000);
        return () => window.clearInterval(id);
    }, [active]);
    return active && seconds >= 3 ? ` ${seconds} s` : '';
}
// Where a page's data will be, while it loads.
export function Loading({ rows = 3, label }) {
    return (_jsx("section", { className: "panel", "aria-busy": "true", "aria-label": label, style: { display: 'flex', flexDirection: 'column', gap: 12 }, children: Array.from({ length: rows }, (_, i) => _jsx("span", { className: "skeleton", style: { width: `${90 - i * 18}%` } }, i)) }));
}
// A page whose data didn't load: the reason and a way to try again (DESIGN.md §1.5).
export function LoadFailed({ error, retry }) {
    return (_jsxs("div", { className: "banner banner-error", role: "alert", children: [_jsxs("span", { children: ["Couldn\u2019t load this: ", error] }), _jsx("button", { type: "button", className: "btn-link", onClick: retry, children: "Try again" })] }));
}
// The running job in the rail, on every page: its step and count.
export function JobLine({ job, queue }) {
    if (!job?.running)
        return null;
    const pct = job.total ? Math.round((job.done / job.total) * 100) : 0;
    return (_jsxs("span", { className: "rail-job", role: "status", "aria-live": "polite", children: [_jsxs("span", { className: "status small", children: [_jsx(Spinner, {}), job.step ?? JOBS[job.name] ?? job.name] }), _jsx("span", { className: "track", "aria-hidden": "true", children: job.total ? _jsx("span", { className: "fill", style: { width: `${pct}%` } }) : _jsx("span", { className: "fill indeterminate" }) }), job.total > 0 && _jsxs("span", { className: "small muted num", children: [job.done.toLocaleString('en-GB'), " of ", job.total.toLocaleString('en-GB')] }), queue?.length ? _jsxs("span", { className: "small muted", children: ["Next: ", queue.map((j) => JOBS[j.name] ?? j.name).join(', then ')] }) : null] }));
}
