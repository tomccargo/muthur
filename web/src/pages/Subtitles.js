import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useState } from 'react';
import { api } from '../api';
import { Dot, Loading } from '../components';
import { count, language } from '../labels';
import { Link } from '../nav';
// What a result has going for it, and against it: a subtitle made for this very file fits; one from the same
// release group, source and resolution usually does; translated or foreign-parts-only ones rarely are what you want.
function Facts({ s }) {
    const facts = [
        s.hearingImpaired && 'for the hard of hearing',
        s.forced && 'foreign parts only',
        s.fps && `${s.fps} fps`,
        s.parts > 1 && `${s.parts} parts`,
        count(s.downloads, 'download'),
        s.votes > 0 && `rated ${s.rating.toFixed(1)} by ${s.votes}`,
        s.uploader && `by ${s.uploader}${s.rank ? ` (${s.rank})` : ''}`,
        s.trusted && 'trusted source',
        s.uploaded,
    ].filter(Boolean);
    return _jsx("span", { className: "small muted", children: facts.join(' · ') });
}
// "Find subtitles" for one video (an episode's menu, a film's page): OpenSubtitles.com searched by the video's IDs and
// its file's fingerprint, the results listed with what helps choose, and only the one picked is downloaded
// (DESIGN.md §1.9: the reader decides, muthur shows why).
export function SubtitleSearch({ path, onSaved }) {
    const [data, setData] = useState(null);
    const [error, setError] = useState(null);
    const [busy, setBusy] = useState(null);
    const [saved, setSaved] = useState(null);
    const [all, setAll] = useState(false);
    useEffect(() => {
        setData(null);
        setError(null);
        api.subtitleSearch(path).then(setData).catch((e) => setError(e.message));
    }, [path]);
    const use = (s) => {
        setBusy(s.fileId);
        setError(null);
        api.subtitleSave(path, s.fileId, s.language)
            .then((r) => {
            setSaved(`Saved as ${r.saved}${r.remaining != null ? ` · ${count(r.remaining, 'download')} left today` : ''}. Kodi finds it the next time the video plays.`);
            onSaved?.(r.saved);
        })
            .catch((e) => setError(e.message))
            .finally(() => setBusy(null));
    };
    if (error) {
        return (_jsxs("div", { className: "banner banner-error", role: "alert", style: { flexDirection: 'column', alignItems: 'flex-start' }, children: [_jsx("span", { children: error }), /Settings/.test(error) && _jsx(Link, { to: "/settings", children: "Open Settings" })] }));
    }
    if (!data)
        return _jsx(Loading, { rows: 3, label: "Searching OpenSubtitles" });
    const shown = all ? data.results : data.results.slice(0, 8);
    return (_jsxs("div", { style: { display: 'flex', flexDirection: 'column', gap: 8 }, children: [saved && _jsx("div", { className: "banner banner-note", role: "status", children: saved }), _jsxs("span", { className: "small muted", children: [data.count ? `${count(data.count, 'subtitle')} on OpenSubtitles for ` : 'Nothing on OpenSubtitles for ', _jsx("span", { className: "mono", children: data.file }), data.count ? ' · made for this file first, then the closest release' : ''] }), data.count > 0 && (_jsx("ul", { className: "rows", children: shown.map((s) => (_jsxs("li", { style: { flexDirection: 'column', alignItems: 'stretch', gap: 3 }, children: [_jsxs("span", { className: "actions", style: { justifyContent: 'space-between', alignItems: 'baseline' }, children: [_jsxs("span", { style: { minWidth: 0 }, children: [_jsx("strong", { children: language(s.language) }), ' ', _jsx("span", { className: "mono small", style: { wordBreak: 'break-all' }, children: s.release })] }), _jsx("button", { className: "btn btn-secondary btn-sm", type: "button", "aria-busy": busy === s.fileId, disabled: busy !== null, onClick: () => use(s), children: "Use this one" })] }), _jsxs("span", { className: "actions", style: { gap: '4px 12px' }, children: [s.hashMatch && _jsxs("span", { className: "status small", children: [_jsx(Dot, { kind: "dot-success" }), "Made for this exact file"] }), !s.hashMatch && s.same.length > 0 && _jsxs("span", { className: "status small", children: [_jsx(Dot, { kind: "dot-success" }), "Same ", s.same.join(' · ')] }), !s.hashMatch && !s.same.length && _jsxs("span", { className: "status small", children: [_jsx(Dot, {}), "Another release: timing may be off"] }), (s.aiTranslated || s.machineTranslated) && (_jsxs("span", { className: "status small", children: [_jsx(Dot, { kind: "dot-warning" }), s.machineTranslated ? 'Machine translated' : 'AI translated'] }))] }), _jsx(Facts, { s: s }), s.comments && _jsxs("span", { className: "small muted", style: { fontStyle: 'italic' }, children: ["\u201C", s.comments, "\u201D"] })] }, s.fileId))) })), data.results.length > shown.length && (_jsxs("button", { type: "button", className: "btn-link small", style: { alignSelf: 'flex-start' }, onClick: () => setAll(true), children: ["Show all ", data.results.length] }))] }));
}
