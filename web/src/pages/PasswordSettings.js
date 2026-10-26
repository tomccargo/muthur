import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from 'react';
import { api, askToSignIn } from '../api';
import { Dot } from '../components';
// muthur's own password: change it (every other browser signs in again), or sign this browser out.
export function PasswordSettings() {
    const [current, setCurrent] = useState('');
    const [next, setNext] = useState('');
    const [busy, setBusy] = useState(false);
    const [state, setState] = useState(null);
    const change = () => {
        setBusy(true);
        setState(null);
        api.changePassword(current, next)
            .then(() => { setCurrent(''); setNext(''); setState({ ok: true, text: 'Changed. Other browsers sign in again with the new password.' }); })
            .catch((e) => setState({ ok: false, text: e.message }))
            .finally(() => setBusy(false));
    };
    const signOut = () => { api.logout().finally(() => askToSignIn('login')); };
    return (_jsxs("section", { className: "panel form", "aria-labelledby": "password-h", children: [_jsx("h2", { id: "password-h", style: { margin: 0, fontSize: '1.15rem', fontWeight: 650 }, children: "Password" }), _jsx("p", { className: "hint", children: "A new password signs every other browser out." }), _jsxs("div", { className: "pair", children: [_jsxs("label", { className: "field-label", children: ["Current password", _jsx("input", { className: "field", type: "password", autoComplete: "current-password", value: current, onChange: (e) => setCurrent(e.target.value) })] }), _jsxs("label", { className: "field-label", children: ["New password", _jsx("input", { className: "field", type: "password", autoComplete: "new-password", value: next, onChange: (e) => setNext(e.target.value) })] })] }), _jsxs("div", { className: "actions", children: [_jsx("button", { className: "btn btn-secondary btn-sm", type: "button", disabled: busy || !current || next.length < 8, "aria-busy": busy, onClick: change, children: "Change the password" }), _jsx("button", { className: "btn btn-secondary btn-sm", type: "button", onClick: signOut, children: "Sign out" }), state && _jsxs("span", { className: "status small", children: [_jsx(Dot, { kind: state.ok ? 'dot-success' : 'dot-danger' }), state.text] })] })] }));
}
