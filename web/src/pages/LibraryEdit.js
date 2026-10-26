import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from 'react';
import { api } from '../api';
import { TitleCard } from './Review';
const IMAGES = 'https://image.tmdb.org/t/p/w185';
// Change a show's or film's match, title or poster (DESIGN.md §13). Each change is a run History can put back.
export function LibraryEditor({ kind, path, nfo, posterTarget, tmdbId, title, onDone }) {
    const [mode, setMode] = useState(null);
    const [query, setQuery] = useState(title);
    const [cards, setCards] = useState(null);
    const [picked, setPicked] = useState(null);
    const [newTitle, setNewTitle] = useState(title);
    const [posters, setPosters] = useState(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState(null);
    const run = (p) => {
        setBusy(true);
        setError(null);
        p.then((r) => { setMode(null); onDone(`${r.label}. It can be put back from History.`); })
            .catch((e) => setError(e.message))
            .finally(() => setBusy(false));
    };
    const open = (m) => {
        setMode(mode === m ? null : m);
        setError(null);
        if (m === 'poster' && tmdbId && !posters)
            api.libraryPosters(kind, tmdbId).then((r) => setPosters(r.posters)).catch((e) => setError(e.message));
    };
    return (_jsxs("div", { style: { display: 'flex', flexDirection: 'column', gap: 10 }, children: [_jsxs("div", { className: "actions", children: [_jsx("button", { className: "btn btn-secondary btn-sm", type: "button", "aria-expanded": mode === 'match', onClick: () => open('match'), children: "Change the match\u2026" }), nfo && _jsx("button", { className: "btn btn-secondary btn-sm", type: "button", "aria-expanded": mode === 'title', onClick: () => open('title'), children: "Change the title\u2026" }), tmdbId && _jsx("button", { className: "btn btn-secondary btn-sm", type: "button", "aria-expanded": mode === 'poster', onClick: () => open('poster'), children: "Choose a poster\u2026" })] }), mode === 'match' && (_jsxs("section", { className: "panel question", "aria-label": "Change the match", children: [_jsxs("p", { className: "hint", children: ["Which ", kind === 'tv' ? 'show' : 'film', " is this? muthur writes its NFO and artwork from the one you pick; the old files are kept for putting back."] }), _jsxs("form", { className: "inline", onSubmit: (e) => { e.preventDefault(); api.search(kind, query).then((r) => { setCards(r.results); setPicked(null); }).catch((x) => setError(x.message)); }, children: [_jsx("input", { className: "field", "aria-label": "Title", value: query, onChange: (e) => setQuery(e.target.value) }), _jsx("button", { className: "btn btn-secondary btn-sm", type: "submit", disabled: !query.trim(), children: "Search TMDB" })] }), cards && (cards.length
                        ? _jsx("div", { className: "cards", children: cards.slice(0, 9).map((c) => _jsx(TitleCard, { card: c, pressed: picked?.tmdbId === c.tmdbId, onPick: () => setPicked(c) }, c.tmdbId)) })
                        : _jsx("p", { className: "hint", children: "Nothing found; try another spelling." })), picked && (_jsxs("button", { className: "btn btn-secondary btn-sm", type: "button", disabled: busy, style: { alignSelf: 'flex-start' }, "aria-busy": busy, onClick: () => run(api.libraryMatch(kind, path, picked.tmdbId)), children: ["It\u2019s ", picked.title, picked.year ? ` (${picked.year})` : ''] }))] })), mode === 'title' && nfo && (_jsxs("section", { className: "panel question", "aria-label": "Change the title", children: [_jsxs("form", { className: "inline", onSubmit: (e) => { e.preventDefault(); run(api.libraryTitle(nfo, newTitle)); }, children: [_jsx("input", { className: "field", "aria-label": "Title", value: newTitle, onChange: (e) => setNewTitle(e.target.value) }), _jsx("button", { className: "btn btn-secondary btn-sm", type: "submit", disabled: busy || !newTitle.trim() || newTitle === title, "aria-busy": busy, children: "Save the title" })] }), _jsx("p", { className: "hint", children: "Changes the title Kodi shows; muthur asks Kodi to re-read it. History can put it back." })] })), mode === 'poster' && (_jsx("section", { className: "panel question", "aria-label": "Choose a poster", children: !posters ? _jsx("p", { className: "hint", children: "Loading TMDB\u2019s posters\u2026" }) : posters.length === 0 ? _jsx("p", { className: "hint", children: "TMDB has no posters for this." }) : (_jsx("div", { className: "posters", children: posters.map((p) => (_jsxs("button", { type: "button", className: "poster-tile", style: { border: 0, background: 'none', padding: 0, cursor: 'pointer' }, disabled: busy, onClick: () => run(api.libraryPoster(posterTarget, p.path)), "aria-label": `Use this poster${p.language ? ` (${p.language})` : ''}`, children: [_jsx("img", { className: "poster", src: IMAGES + p.path, alt: "", loading: "lazy" }), _jsx("span", { className: "small muted", children: p.language ?? 'no text' })] }, p.path))) })) })), error && _jsx("div", { className: "banner banner-error", role: "alert", children: error })] }));
}
