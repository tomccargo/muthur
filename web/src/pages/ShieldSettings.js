import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from 'react';
import { api } from '../api';
import { Dot, HowTo, useElapsed } from '../components';
// Waking the Kodi box (an Android TV device) and starting Kodi over network debugging. The app list comes from the box itself.
export function ShieldSettings({ draft, edit, device }) {
    const [apps, setApps] = useState(null);
    const [current, setCurrent] = useState(null);
    const [state, setState] = useState(null);
    const [busy, setBusy] = useState(null);
    const took = useElapsed(busy !== null);
    const load = () => {
        setBusy('apps');
        setState(null);
        api.shieldApps()
            .then((r) => { setApps(r.apps); setCurrent(r.current); setState({ ok: true, text: `Connected · ${r.apps.length} apps on the ${device}` }); })
            .catch((e) => setState({ ok: false, text: e.message }))
            .finally(() => setBusy(null));
    };
    const wake = () => {
        setBusy('wake');
        setState(null);
        api.wakeShield()
            .then((r) => setState({ ok: true, text: r.note ?? `The ${device} is awake and Kodi answers.` }))
            .catch((e) => setState({ ok: false, text: e.message }))
            .finally(() => setBusy(null));
    };
    const onScreen = apps?.find((a) => current && a.startsWith(current + '/'));
    return (_jsxs("div", { style: { display: 'flex', flexDirection: 'column', gap: 10, paddingTop: 12, borderTop: '1px solid var(--border)' }, children: [_jsxs("h3", { style: { margin: 0, fontSize: '1rem', fontWeight: 650 }, children: ["Waking the ", device] }), _jsxs(HowTo, { children: ["When you start something that needs Kodi (Apply, Duplicates, a restore) and the ", device, " sleeps, muthur wakes it and starts Kodi first. This uses network debugging (Device Preferences, Developer options). The first time, the TV asks to allow muthur: tick \u201CAlways allow\u201D. Only things you start wake it; the scheduled checks never do. Waking may switch the TV on and to the ", device, " (HDMI-CEC)."] }), _jsxs("label", { className: "choice", children: [_jsx("input", { type: "checkbox", checked: draft.shieldOn, onChange: (e) => edit({ shieldOn: e.target.checked }) }), _jsxs("span", { children: ["Wake the ", device, " when Kodi is needed"] })] }), _jsxs("div", { className: "pair", children: [_jsxs("label", { className: "field-label", children: ["Network debugging port", _jsx("input", { className: "field", type: "text", inputMode: "numeric", value: draft.shieldPort, onChange: (e) => edit({ shieldPort: e.target.value }) })] }), _jsxs("label", { className: "field-label", children: ["App to start", _jsxs("select", { className: "field", value: draft.shieldApp, onChange: (e) => edit({ shieldApp: e.target.value }), children: [!draft.shieldApp && _jsxs("option", { value: "", children: ["Choose after reading the ", device, "\u2019s apps"] }), draft.shieldApp && !(apps ?? []).includes(draft.shieldApp) && _jsx("option", { value: draft.shieldApp, children: draft.shieldApp.split('/')[0] }), (apps ?? []).map((a) => _jsxs("option", { value: a, children: [a.split('/')[0], a === onScreen ? ' (on screen now)' : ''] }, a))] })] })] }), _jsxs("div", { className: "actions", children: [_jsxs("button", { className: "btn btn-secondary btn-sm", type: "button", disabled: busy !== null, "aria-busy": busy === 'apps', onClick: load, children: ["Read the ", device, "\u2019s apps"] }), onScreen && draft.shieldApp !== onScreen && (_jsxs("button", { className: "btn btn-secondary btn-sm", type: "button", onClick: () => edit({ shieldApp: onScreen }), children: ["Use the app on screen (", onScreen.split('/')[0], ")"] })), _jsxs("button", { className: "btn btn-secondary btn-sm", type: "button", disabled: busy !== null || !draft.shieldApp, "aria-busy": busy === 'wake', onClick: wake, children: ["Wake the ", device, " now"] }), busy && _jsxs("span", { className: "small muted", children: ["Talking to the ", device, "\u2026", took] }), state && _jsxs("span", { className: "status small", children: [_jsx(Dot, { kind: state.ok ? 'dot-success' : 'dot-danger' }), state.text] })] })] }));
}
