import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { lazy, Suspense, useCallback, useEffect, useState } from 'react';
import { AUTH_EVENT, api } from './api';
import { Icon } from './icons';
import { Backdrop } from './Backdrop';
import { JobBar, JobLine, Spinner } from './components';
import { when } from './labels';
import { Link, useLocation } from './nav';
import { useTheme } from './theme';
import { Dashboard } from './pages/Dashboard';
import { InboxPage } from './pages/Inbox';
import { SettingsPage } from './pages/Settings';
import { HistoryPage } from './pages/History';
import { ReviewPage } from './pages/Review';
import { LibraryPage } from './pages/Library';
import { DuplicatesPage } from './pages/Duplicates';
import { HealthPage } from './pages/Health';
import { SignIn } from './pages/SignIn';
// The player is its own page (docs/PLAYER.md), loaded only when opened.
const PlayerApp = lazy(() => import('./pages/Player'));
// Five sections, one per job (DESIGN.md §1.4): the downloads, the library, what muthur did, and how it works.
// Downloads and Library hold their pages as tabs. Only pages that exist are in the navigation (§1.5).
const SECTIONS = [
    { to: '/', label: 'Dashboard', icon: 'dashboard', paths: ['/'] },
    { to: '/inbox', label: 'Downloads', icon: 'inbox', paths: ['/inbox', '/review'] },
    { to: '/library', label: 'Library', icon: 'library', paths: ['/library', '/duplicates'] },
    // Its own place, not a tab under Library: what needs fixing is found from anywhere (DESIGN.md §1.4).
    { to: '/health', label: 'Health', icon: 'health', paths: ['/health'] },
    { to: '/history', label: 'History', icon: 'history', paths: ['/history'] },
    { to: '/settings', label: 'Settings', icon: 'settings', paths: ['/settings'] },
];
const TABS = {
    '/inbox': [{ to: '/inbox', label: 'Inbox' }, { to: '/review', label: 'Review' }],
    '/library': [{ to: '/library', label: 'Shows and films' }, { to: '/duplicates', label: 'Duplicates' }],
};
const TITLES = {
    '/inbox': 'Inbox', '/review': 'Review', '/library': 'Library', '/duplicates': 'Duplicates', '/health': 'Health', '/history': 'History', '/settings': 'Settings',
};
function useStatus() {
    const [status, setStatus] = useState(null);
    const [error, setError] = useState(null);
    const refresh = useCallback(() => {
        api.status().then((s) => { setStatus(s); setError(null); }).catch((e) => setError(e.message));
    }, []);
    useEffect(() => {
        refresh();
        // Faster while a job runs, so its progress is visible; slow otherwise.
        const id = window.setInterval(refresh, status?.job?.running ? 1000 : 15000);
        return () => window.clearInterval(id);
    }, [refresh, status?.job?.running]);
    return { status, error, refresh };
}
function ThemeSwitch() {
    const [theme, setTheme] = useTheme();
    const options = [['system', 'monitor', 'Follow the system'], ['dark', 'moon', 'Dark'], ['light', 'sun', 'Light']];
    return (_jsx("div", { className: "seg", role: "group", "aria-label": "Theme", children: options.map(([value, icon, label]) => (_jsx("button", { type: "button", "aria-pressed": theme === value, "aria-label": label, title: label, onClick: () => setTheme(value), children: _jsx(Icon, { name: icon, size: 15 }) }, value))) }));
}
function RailFoot({ status, onChange }) {
    const k = status?.kodi;
    const [waking, setWaking] = useState(false);
    return (_jsxs("div", { className: "rail-foot", children: [_jsx(JobLine, { job: status?.job, queue: status?.queue }), k === undefined ? null : k === null ? (_jsxs("span", { className: "status", children: [_jsx("span", { className: "dot" }), "Kodi not set up"] })) : k.connected ? (_jsxs("span", { className: "status", children: [_jsx("span", { className: "dot dot-success" }), status?.names.device, " \u00B7 Kodi ", k.version] })) : (_jsxs("span", { className: "status", children: [_jsx("span", { className: "dot dot-danger" }), "Kodi unreachable", k.canWake && (waking ? _jsxs("span", { className: "small", children: [_jsx(Spinner, {}), " Waking\u2026"] })
                        : _jsx("button", { type: "button", className: "btn-link small", onClick: () => { setWaking(true); api.wakeShield().catch(() => undefined).finally(() => { setWaking(false); onChange(); }); }, children: "Wake" }))] })), status && !status.applying && _jsxs("span", { className: "status", children: [_jsx("span", { className: "dot dot-warning" }), "Dry run on"] }), status?.watched.paused ? _jsxs("span", { className: "status", children: [_jsx("span", { className: "dot dot-danger" }), "Watched backup paused"] })
                : status?.watched.last ? _jsxs("span", { className: "status", children: [_jsx("span", { className: "dot dot-success" }), "Backed up ", when(status.watched.last.at)] }) : null, _jsx(ThemeSwitch, {})] }));
}
// Signed in first (ARCHITECTURE.md §14); the app itself only once the server says this browser may.
export function App() {
    const [auth, setAuth] = useState('checking');
    useEffect(() => {
        api.auth().then((a) => setAuth(a.signedIn ? 'ok' : a.set ? 'login' : 'setup')).catch(() => setAuth('ok'));
        const onAuth = (e) => setAuth(e.detail);
        window.addEventListener(AUTH_EVENT, onAuth);
        return () => window.removeEventListener(AUTH_EVENT, onAuth);
    }, []);
    if (auth === 'checking')
        return null;
    if (auth !== 'ok')
        return _jsx(SignIn, { mode: auth, onDone: () => setAuth('ok') });
    return _jsx(Pages, {});
}
function Pages() {
    const { path } = useLocation();
    if (path === '/player' || path.startsWith('/player/'))
        return _jsx(Suspense, { fallback: null, children: _jsx(PlayerApp, {}) });
    return _jsx(Shell, {});
}
// On a phone the rail's status isn't there: one dot in the top bar says whether Kodi and the backup are fine.
function StatusDot({ status }) {
    const k = status?.kodi;
    const text = !k ? 'Kodi not set up' : !k.connected ? 'Kodi unreachable' : status?.watched.paused ? 'Watched backup paused'
        : `${status?.names.device} · Kodi ${k.version}`;
    const kind = !k ? '' : k.connected && !status?.watched.paused ? 'dot-success' : 'dot-danger';
    if (status?.job?.running) {
        const what = status.job.step ?? status.job.name;
        return _jsx(Link, { to: "/", className: "topbar-status", "aria-label": `Working: ${what}`, title: `Working: ${what}`, children: _jsx(Spinner, {}) });
    }
    return _jsx(Link, { to: "/settings", className: "topbar-status", "aria-label": text, title: text, children: _jsx("span", { className: `dot ${kind}` }) });
}
function Shell() {
    const { path } = useLocation();
    const hook = useStatus();
    const counts = hook.status?.inbox.counts ?? {};
    const counter = { '/inbox': counts.ready ?? 0, '/review': counts.review ?? 0, '/duplicates': hook.status?.duplicates ?? 0, '/health': hook.status?.fixes ?? 0 };
    const page = path in TITLES ? path : '/';
    const current = SECTIONS.find((s) => s.paths.includes(page)) ?? SECTIONS[0];
    const total = (s) => s.paths.reduce((n, p) => n + (counter[p] ?? 0), 0);
    useEffect(() => {
        document.title = page === '/' ? 'muthur' : `${TITLES[page]} · muthur`;
    }, [page]);
    return (_jsxs("div", { className: "shell", children: [_jsx(Backdrop, {}), _jsx(JobBar, { job: hook.status?.job }), _jsx("a", { className: "skip-link", href: "#main", children: "Skip to the page" }), _jsxs("nav", { className: "rail", "aria-label": "Main", children: [_jsxs(Link, { to: "/", className: "brand", "aria-label": "muthur, dashboard", children: [_jsx("span", { className: "brand-mark", "aria-hidden": "true" }), _jsxs("span", { children: [_jsx("span", { className: "brand-name", children: "MU/TH/UR" }), _jsx("br", {}), _jsx("span", { className: "brand-sub", children: hook.status?.names.nas ? `muthur · ${hook.status.names.nas.toLowerCase()}` : 'muthur' })] })] }), _jsx("div", { className: "rail-nav", children: SECTIONS.map((s) => (_jsxs(Link, { to: s.to, className: "rail-link", "aria-current": current.to === s.to ? 'page' : undefined, children: [_jsx(Icon, { name: s.icon }), s.label, total(s) > 0 && _jsx("span", { className: "counter", children: total(s) })] }, s.to))) }), _jsx(RailFoot, { status: hook.status, onChange: hook.refresh })] }), _jsxs("header", { className: "topbar", children: [_jsxs(Link, { to: "/", className: "brand", "aria-label": "muthur, dashboard", children: [_jsx("span", { className: "brand-mark", "aria-hidden": "true" }), _jsx("span", { className: "brand-name", children: "MU/TH/UR" })] }), _jsx(StatusDot, { status: hook.status }), _jsx(ThemeSwitch, {})] }), _jsxs("main", { className: "main", id: "main", tabIndex: -1, children: [TABS[current.to] && (_jsx("nav", { className: "section-tabs", "aria-label": current.label, children: TABS[current.to].map((t) => (_jsxs(Link, { to: t.to, className: "section-tab", "aria-current": page === t.to ? 'page' : undefined, children: [t.label, (counter[t.to] ?? 0) > 0 && _jsx("span", { className: "counter", children: counter[t.to] })] }, t.to))) })), page === '/' && _jsx(Dashboard, { ...hook }), page === '/inbox' && _jsx(InboxPage, { ...hook }), page === '/review' && _jsx(ReviewPage, { ...hook }), page === '/library' && _jsx(LibraryPage, { ...hook }), page === '/duplicates' && _jsx(DuplicatesPage, { ...hook }), page === '/health' && _jsx(HealthPage, { ...hook }), page === '/history' && _jsx(HistoryPage, { ...hook }), page === '/settings' && _jsx(SettingsPage, { ...hook })] }), _jsx("nav", { className: "tabbar", "aria-label": "Main", children: SECTIONS.map((s) => (_jsxs(Link, { to: s.to, className: "tab", "aria-current": current.to === s.to ? 'page' : undefined, children: [_jsx(Icon, { name: s.icon, size: 20 }), s.label] }, s.to))) })] }));
}
