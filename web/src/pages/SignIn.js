import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from 'react';
import { api } from '../api';
// The first visit chooses muthur's password; after that a browser signs in with it (ARCHITECTURE.md §14).
export function SignIn({ mode, onDone }) {
    const [password, setPassword] = useState('');
    const [again, setAgain] = useState('');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState(null);
    const setup = mode === 'setup';
    const submit = (e) => {
        e.preventDefault();
        if (setup && password !== again) {
            setError('The two passwords differ.');
            return;
        }
        setBusy(true);
        setError(null);
        (setup ? api.setup(password) : api.login(password))
            .then(onDone)
            .catch((x) => setError(x.message))
            .finally(() => setBusy(false));
    };
    return (_jsx("main", { className: "main", id: "main", style: { marginLeft: 0 }, children: _jsxs("div", { className: "page", style: { maxWidth: 460 }, children: [_jsx("header", { className: "page-head", children: _jsxs("div", { children: [_jsx("p", { className: "eyebrow", children: "muthur" }), _jsx("h1", { children: setup ? 'Choose a password' : 'Sign in' }), _jsx("p", { className: "lede", children: setup
                                    ? 'muthur moves, renames and deletes files. A password keeps others on your network, and other websites you visit, from doing that through this page.'
                                    : 'muthur asks once per browser, and again after 30 days without a visit.' })] }) }), _jsxs("form", { className: "panel form", onSubmit: submit, children: [_jsxs("label", { className: "field-label", children: ["Password", _jsx("input", { className: "field", type: "password", autoComplete: setup ? 'new-password' : 'current-password', autoFocus: true, value: password, onChange: (e) => setPassword(e.target.value) })] }), setup && (_jsxs("label", { className: "field-label", children: ["The same password again", _jsx("input", { className: "field", type: "password", autoComplete: "new-password", value: again, onChange: (e) => setAgain(e.target.value) })] })), error && _jsx("div", { className: "banner banner-error", role: "alert", children: error }), _jsx("div", { className: "actions", children: _jsx("button", { className: "btn btn-primary", type: "submit", disabled: busy || !password || (setup && !again), "aria-busy": busy, children: setup ? 'Save the password' : 'Sign in' }) }), _jsxs("p", { className: "hint", children: [setup ? 'At least 8 characters. ' : '', "Forgotten? In Container Manager, open muthur\u2019s terminal and type ", _jsx("span", { className: "mono", children: "muthur password" }), " to choose a new one."] })] })] }) }));
}
