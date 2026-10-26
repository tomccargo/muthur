import { Fragment as _Fragment, jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useState } from 'react';
import { api } from '../api';
import { Dot, HowTo, Loading } from '../components';
import { PasswordSettings } from './PasswordSettings';
import { ShieldSettings } from './ShieldSettings';
import { ALL_LANGUAGES, METADATA_LANGUAGES, language, libraryPath, metadataLanguage } from '../labels';
function toDraft(s) {
    return {
        host: s.kodi.host, port: String(s.kodi.port), tcpPort: String(s.kodi.tcpPort), user: s.kodi.user, password: '', token: '',
        tmdbLanguage: s.tmdb.language, keepOriginal: s.titles.keepOriginal,
        dsUrl: s.downloadStation.url, dsUser: s.downloadStation.user, dsPassword: '', dryRun: s.dryRun, preferHdr: s.quality.preferHdr,
        shieldOn: s.shield.enabled, shieldPort: String(s.shield.port), shieldApp: s.shield.app, device: s.names.device, nas: s.names.nas,
        osKey: '', osUser: s.openSubtitles.user, osPassword: '',
    };
}
export function SettingsPage({ refresh }) {
    const [saved, setSaved] = useState(null);
    const [draft, setDraft] = useState(null);
    const [dirty, setDirty] = useState(false);
    const [message, setMessage] = useState(null);
    const [kodi, setKodi] = useState(null);
    const [testing, setTesting] = useState(false);
    const [ds, setDs] = useState(null);
    const [os, setOs] = useState(null);
    useEffect(() => {
        api.settings().then((s) => { setSaved(s); setDraft(toDraft(s)); }).catch((e) => setMessage({ kind: 'error', text: e.message }));
    }, []);
    if (!draft || !saved) {
        return _jsx("div", { className: "page", children: message ? _jsx("div", { className: "banner banner-error", role: "alert", children: message.text }) : _jsx(Loading, { rows: 5, label: "Loading the settings" }) });
    }
    const edit = (patch) => { setDraft({ ...draft, ...patch }); setDirty(true); setMessage(null); };
    const toggle = (code) => edit({ keepOriginal: draft.keepOriginal.includes(code) ? draft.keepOriginal.filter((c) => c !== code) : [...draft.keepOriginal, code] });
    const save = () => {
        const body = {
            kodi: { host: draft.host, port: draft.port, tcpPort: draft.tcpPort, user: draft.user, ...(draft.password ? { password: draft.password } : {}) },
            titles: { keepOriginal: draft.keepOriginal },
            downloadStation: dsBody(),
            openSubtitles: osBody(),
            dryRun: draft.dryRun,
            shield: { enabled: draft.shieldOn, port: draft.shieldPort, app: draft.shieldApp },
            quality: { preferHdr: draft.preferHdr },
            names: { device: draft.device, nas: draft.nas },
            tmdb: { language: draft.tmdbLanguage, ...(draft.token ? { token: draft.token } : {}) },
        };
        api.saveSettings(body)
            .then((s) => { setSaved(s); setDraft(toDraft(s)); setDirty(false); refresh(); })
            .catch((e) => setMessage({ kind: 'error', text: e.message }));
    };
    function osBody() {
        return { user: draft.osUser, ...(draft.osKey ? { apiKey: draft.osKey } : {}), ...(draft.osPassword ? { password: draft.osPassword } : {}) };
    }
    const testOs = () => {
        setOs(null);
        const go = dirty ? api.saveSettings({ openSubtitles: osBody() }) : Promise.resolve(saved);
        go.then(() => api.testOpenSubtitles()).then(setOs).catch((e) => setOs({ ok: false, problem: e.message }));
    };
    function dsBody() {
        return { url: draft.dsUrl, user: draft.dsUser, ...(draft.dsPassword ? { password: draft.dsPassword } : {}) };
    }
    const testDs = () => {
        setDs(null);
        const go = dirty ? api.saveSettings({ downloadStation: dsBody() }) : Promise.resolve(saved);
        go.then(() => api.testDownloadStation()).then(setDs).catch((e) => setDs({ connected: false, problem: e.message }));
    };
    // Removing a saved secret saves at once: it is its own action, not part of the draft.
    const forget = (body) => {
        api.saveSettings(body)
            .then((s) => { setSaved(s); setDraft(toDraft(s)); setDirty(false); refresh(); })
            .catch((e) => setMessage({ kind: 'error', text: e.message }));
    };
    const test = () => {
        setTesting(true);
        setKodi(null);
        const go = dirty ? api.saveSettings({ kodi: { host: draft.host, port: draft.port, user: draft.user, ...(draft.password ? { password: draft.password } : {}) } }) : Promise.resolve(saved);
        go.then(() => api.testKodi()).then(setKodi).catch((e) => setKodi({ connected: false, problem: e.message })).finally(() => setTesting(false));
    };
    return (_jsxs("div", { className: "page", children: [_jsxs("header", { className: "page-head", children: [_jsxs("div", { children: [_jsx("p", { className: "eyebrow", children: "How muthur works" }), _jsx("h1", { children: "Settings" })] }), _jsxs("div", { className: "actions", children: [dirty && _jsxs("span", { className: "status small muted", children: [_jsx(Dot, { kind: "dot-warning" }), "Unsaved changes"] }), _jsx("button", { className: "btn btn-primary", type: "button", onClick: save, disabled: !dirty, children: "Save" })] })] }), message && _jsx("div", { className: `banner banner-${message.kind}`, role: "alert", children: message.text }), _jsxs("section", { className: "panel form", "aria-labelledby": "changes-h", children: [_jsx("h2", { id: "changes-h", style: { margin: 0, fontSize: '1.15rem', fontWeight: 650 }, children: "Changes to the library" }), _jsxs("label", { className: "choice", children: [_jsx("input", { type: "checkbox", checked: draft.dryRun, onChange: (e) => edit({ dryRun: e.target.checked }) }), _jsxs("span", { children: ["Dry run ", _jsx("span", { className: "muted", children: "\u00B7 plans only, changes nothing" })] })] }), _jsxs("label", { className: "choice", children: [_jsx("input", { type: "checkbox", checked: draft.preferHdr, onChange: (e) => edit({ preferHdr: e.target.checked }) }), _jsx("span", { children: "Prefer HDR copies when resolving duplicates" })] })] }), _jsxs("section", { className: "panel form", "aria-labelledby": "tmdb-h", children: [_jsx("h2", { id: "tmdb-h", style: { margin: 0, fontSize: '1.15rem', fontWeight: 650 }, children: "TMDB" }), _jsx(HowTo, { children: "A personal token is free: on themoviedb.org go to Settings, then API, and copy the \u201CAPI Read Access Token\u201D." }), _jsxs("div", { className: "actions", children: [_jsx("span", { className: "status small", children: saved.tmdb.tokenFrom === 'settings' ? _jsxs(_Fragment, { children: [_jsx(Dot, { kind: "dot-success" }), "A token is saved"] })
                                    : saved.tmdb.tokenFrom === 'install' ? _jsxs(_Fragment, { children: [_jsx(Dot, { kind: "dot-success" }), "A token comes from the install settings (.env)"] })
                                        : _jsxs(_Fragment, { children: [_jsx(Dot, { kind: "dot-danger" }), "No token yet"] }) }), saved.tmdb.tokenFrom === 'settings' && !dirty && (_jsx("button", { className: "btn btn-secondary btn-sm", type: "button", onClick: () => forget({ tmdb: { forget: true } }), children: "Remove the saved token" }))] }), _jsxs("label", { className: "field-label", children: [saved.tmdb.tokenSet ? 'Replace the token' : 'Token', _jsx("input", { className: "field", type: "password", autoComplete: "off", value: draft.token, onChange: (e) => edit({ token: e.target.value }) })] }), _jsxs("label", { className: "field-label", children: ["Language of plots, genres and episode titles", _jsx("select", { className: "field", value: draft.tmdbLanguage, onChange: (e) => edit({ tmdbLanguage: e.target.value }), children: METADATA_LANGUAGES.map((code) => _jsx("option", { value: code, children: metadataLanguage(code) }, code)) })] })] }), _jsxs("section", { className: "panel form", "aria-labelledby": "kodi-h", children: [_jsxs("h2", { id: "kodi-h", style: { margin: 0, fontSize: '1.15rem', fontWeight: 650 }, children: ["Kodi on the ", saved.names.device] }), _jsx(HowTo, { children: "In Kodi: Settings, Services, Control, then turn on \u201CAllow remote control via HTTP\u201D and set a username and password." }), _jsxs("label", { className: "field-label", children: ["The ", saved.names.device, "\u2019s address", _jsx("input", { className: "field", type: "text", placeholder: "for example 192.168.1.20", value: draft.host, onChange: (e) => edit({ host: e.target.value }) })] }), _jsxs("div", { className: "pair", children: [_jsxs("label", { className: "field-label", children: ["Port", _jsx("input", { className: "field", type: "text", inputMode: "numeric", value: draft.port, onChange: (e) => edit({ port: e.target.value }) })] }), _jsxs("label", { className: "field-label", children: ["Username", _jsx("input", { className: "field", type: "text", autoComplete: "off", value: draft.user, onChange: (e) => edit({ user: e.target.value }) })] })] }), _jsxs("label", { className: "field-label", children: [saved.kodi.passwordSet ? 'Password (saved; type to replace it)' : 'Password', _jsx("input", { className: "field", type: "password", autoComplete: "off", value: draft.password, onChange: (e) => edit({ password: e.target.value }) })] }), _jsxs("label", { className: "field-label", children: ["Port for notifications", _jsx("input", { className: "field", type: "text", inputMode: "numeric", value: draft.tcpPort, onChange: (e) => edit({ tcpPort: e.target.value }) }), _jsx("span", { className: "hint", children: "9090 unless you changed it in Kodi. muthur hears through it when something was watched." })] }), _jsxs("div", { className: "actions", children: [_jsx("button", { className: "btn btn-secondary btn-sm", type: "button", onClick: test, disabled: testing || !draft.host, "aria-busy": testing, children: testing ? 'Testing…' : 'Test the connection' }), kodi && (kodi.connected
                                ? _jsxs("span", { className: "status small", children: [_jsx(Dot, { kind: "dot-success" }), "Connected \u00B7 Kodi ", kodi.version] })
                                : _jsxs("span", { className: "status small", children: [_jsx(Dot, { kind: "dot-danger" }), kodi.problem] }))] }), _jsx(ShieldSettings, { draft: draft, edit: edit, device: saved.names.device })] }), _jsxs("section", { className: "panel form", "aria-labelledby": "ds-h", children: [_jsx("h2", { id: "ds-h", style: { margin: 0, fontSize: '1.15rem', fontWeight: 650 }, children: "Download Station" }), _jsx(HowTo, { children: "After a download is moved into the library, muthur removes its finished task from Download Station, so it doesn\u2019t keep pointing at files that are gone. Use the DSM account that adds the downloads, because Download Station only shows an account its own tasks; it must not use two-step verification. Leave this empty to keep tasks as they are." }), _jsxs("label", { className: "field-label", children: ["The NAS\u2019s address", _jsx("input", { className: "field", type: "text", placeholder: "for example http://192.168.1.10:5000", value: draft.dsUrl, onChange: (e) => edit({ dsUrl: e.target.value }) })] }), _jsxs("div", { className: "pair", children: [_jsxs("label", { className: "field-label", children: ["DSM account", _jsx("input", { className: "field", type: "text", autoComplete: "off", value: draft.dsUser, onChange: (e) => edit({ dsUser: e.target.value }) })] }), _jsxs("label", { className: "field-label", children: [saved.downloadStation.passwordSet ? 'Password (saved)' : 'Password', _jsx("input", { className: "field", type: "password", autoComplete: "off", value: draft.dsPassword, onChange: (e) => edit({ dsPassword: e.target.value }) })] })] }), _jsxs("div", { className: "actions", children: [_jsx("button", { className: "btn btn-secondary btn-sm", type: "button", onClick: testDs, disabled: !draft.dsUrl || !draft.dsUser, children: "Test the connection" }), (saved.downloadStation.url || saved.downloadStation.user) && !dirty && (_jsx("button", { className: "btn btn-secondary btn-sm", type: "button", onClick: () => forget({ downloadStation: { forget: true } }), children: "Forget this account" })), ds && (ds.connected
                                ? _jsxs("span", { className: "status small", children: [_jsx(Dot, { kind: "dot-success" }), "Connected \u00B7 ", ds.tasks, " tasks"] })
                                : _jsxs("span", { className: "status small", children: [_jsx(Dot, { kind: "dot-danger" }), ds.problem] }))] })] }), _jsxs("section", { className: "panel form", "aria-labelledby": "os-h", children: [_jsx("h2", { id: "os-h", style: { margin: 0, fontSize: '1.15rem', fontWeight: 650 }, children: "Subtitles from OpenSubtitles.com" }), _jsx(HowTo, { children: "For \u201CFind subtitles\u201D on an episode or a film. Make an account on opensubtitles.com (free: 20 downloads a day; VIP: 1000). In your profile, under \u201CAPI consumers\u201D, add one (any name, for example muthur) and copy its API key here, with your username and password. muthur only downloads the subtitle you pick." }), _jsxs("label", { className: "field-label", children: [saved.openSubtitles.apiKeySet ? 'API key (saved)' : 'API key', _jsx("input", { className: "field", type: "password", autoComplete: "off", value: draft.osKey, onChange: (e) => edit({ osKey: e.target.value }) })] }), _jsxs("div", { className: "pair", children: [_jsxs("label", { className: "field-label", children: ["Username", _jsx("input", { className: "field", type: "text", autoComplete: "off", value: draft.osUser, onChange: (e) => edit({ osUser: e.target.value }) })] }), _jsxs("label", { className: "field-label", children: [saved.openSubtitles.passwordSet ? 'Password (saved)' : 'Password', _jsx("input", { className: "field", type: "password", autoComplete: "off", value: draft.osPassword, onChange: (e) => edit({ osPassword: e.target.value }) })] })] }), _jsxs("div", { className: "actions", children: [_jsx("button", { className: "btn btn-secondary btn-sm", type: "button", onClick: draft.osUser && (draft.osKey || saved.openSubtitles.apiKeySet) ? testOs : undefined, ...(!draft.osUser || !(draft.osKey || saved.openSubtitles.apiKeySet) ? { 'aria-disabled': true, title: 'Enter the API key and the username first' } : {}), children: "Test the account" }), (saved.openSubtitles.user || saved.openSubtitles.apiKeySet) && !dirty && (_jsx("button", { className: "btn btn-secondary btn-sm", type: "button", onClick: () => forget({ openSubtitles: { forget: true } }), children: "Forget this account" })), os && (os.ok
                                ? _jsxs("span", { className: "status small", children: [_jsx(Dot, { kind: "dot-success" }), "Signed in \u00B7 ", os.level ?? 'account', os.allowed != null ? ` · ${os.allowed} downloads a day` : ''] })
                                : _jsxs("span", { className: "status small", children: [_jsx(Dot, { kind: "dot-danger" }), os.problem] }))] })] }), _jsxs("section", { className: "panel form", "aria-labelledby": "titles-h", children: [_jsx("h2", { id: "titles-h", style: { margin: 0, fontSize: '1.15rem', fontWeight: 650 }, children: "Which films keep their original title?" }), _jsx("p", { className: "hint", children: "On: the original title (Aguirre, der Zorn Gottes). Off: the English title (Spirited Away)." }), _jsx("div", { style: { display: 'flex', flexWrap: 'wrap', gap: 8 }, children: ALL_LANGUAGES.map((code) => (_jsx("button", { type: "button", className: "chip", "aria-pressed": draft.keepOriginal.includes(code), onClick: () => toggle(code), children: language(code) }, code))) })] }), _jsxs("section", { className: "panel form", "aria-labelledby": "names-h", children: [_jsx("h2", { id: "names-h", style: { margin: 0, fontSize: '1.15rem', fontWeight: 650 }, children: "Names" }), _jsxs("div", { className: "pair", children: [_jsxs("label", { className: "field-label", children: ["Your NAS", _jsx("input", { className: "field", type: "text", maxLength: 40, placeholder: "NAS", value: draft.nas, onChange: (e) => edit({ nas: e.target.value }) })] }), _jsxs("label", { className: "field-label", children: ["The device Kodi runs on", _jsx("input", { className: "field", type: "text", maxLength: 40, placeholder: "Kodi device", value: draft.device, onChange: (e) => edit({ device: e.target.value }) })] })] })] }), _jsx(PasswordSettings, {}), _jsxs("section", { className: "panel form", "aria-labelledby": "dirs-h", children: [_jsx("h2", { id: "dirs-h", style: { margin: 0, fontSize: '1.15rem', fontWeight: 650 }, children: "Folders" }), _jsxs("ul", { className: "rows", children: [_jsxs("li", { children: [_jsx("span", { children: "Finished downloads" }), _jsx("span", { className: "mono small", style: { overflowWrap: 'anywhere' }, children: libraryPath(saved.paths.downloads) })] }), _jsxs("li", { children: [_jsx("span", { children: "TV" }), _jsx("span", { className: "mono small", style: { overflowWrap: 'anywhere' }, children: libraryPath(saved.paths.tv) })] }), _jsxs("li", { children: [_jsx("span", { children: "Film" }), _jsx("span", { className: "mono small", style: { overflowWrap: 'anywhere' }, children: libraryPath(saved.paths.film) })] })] })] })] }));
}
