import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import { Dot, JobError, Loading } from '../components';
import { SIGNALS, hue, middle, splitId } from '../labels';
import { Link } from '../nav';
const IMAGES = 'https://image.tmdb.org/t/p/w185';
const code = (s, e) => `S${String(s).padStart(2, '0')}${(Array.isArray(e) ? e : [e]).map((n) => `E${String(n).padStart(2, '0')}`).join('')}`;
const aired = (d) => (d ? new Date(d).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }) : '');
// A missing poster gets the title's initials on the title's own tint (DESIGN.md §8), never a broken image.
export function Poster({ path, title }) {
    const [failed, setFailed] = useState(false);
    if (!path || failed) {
        const initials = title.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join('').toUpperCase();
        return _jsx("span", { className: "poster", style: { '--hue': hue(title) }, "aria-hidden": "true", children: _jsx("span", { className: "poster-initials", children: initials || '?' }) });
    }
    return _jsx("img", { className: "poster", src: IMAGES + path, alt: "", loading: "lazy", onError: () => setFailed(true) });
}
export function TitleCard({ card, pressed, onPick }) {
    const why = Object.entries(card.signals ?? {}).filter(([k]) => k !== 'popularity').map(([k, v]) => `${SIGNALS[k] ?? k} ${Math.round(v * 100)}%`);
    return (_jsxs("button", { type: "button", className: "card", "aria-pressed": pressed, onClick: onPick, children: [_jsx(Poster, { path: card.poster, title: card.title }), _jsxs("span", { style: { display: 'flex', flexDirection: 'column', gap: 3, minWidth: 0 }, children: [_jsxs("strong", { style: { overflowWrap: 'anywhere' }, children: [card.title, card.year ? ` (${card.year})` : ''] }), card.originalTitle && card.originalTitle !== card.title && _jsx("span", { className: "small muted", children: card.originalTitle }), card.overview && _jsx("span", { className: "small clamp", children: card.overview }), why.length > 0 && _jsx("span", { className: "small muted", children: why.join(' · ') })] })] }));
}
// ---- Which show or film is this? -------------------------------------------------------------
function IdentityQuestion({ item, busy, onChosen }) {
    const suggested = useMemo(() => item.candidates.map((c) => ({
        kind: (item.kind ?? 'movie'), tmdbId: c.tmdbId, title: c.title, originalTitle: c.originalTitle, year: c.year,
        overview: c.overview ?? '', poster: c.poster ?? null, signals: c.signals,
    })), [item]);
    const [kind, setKind] = useState((item.kind ?? 'movie'));
    const [query, setQuery] = useState(item.parsed?.title ?? splitId(item.id).name);
    const [year, setYear] = useState(item.parsed?.year ? String(item.parsed.year) : '');
    const [link, setLink] = useState('');
    const [found, setFound] = useState(null);
    const [picked, setPicked] = useState(null);
    const [remember, setRemember] = useState(true);
    const [error, setError] = useState(null);
    const cards = found?.cards ?? suggested;
    const search = () => {
        setError(null);
        api.search(kind, query, year ? Number(year) : undefined)
            .then((r) => { setFound({ label: `Results for “${query}”${year ? ` (${year})` : ''}`, cards: r.results }); setPicked(null); })
            .catch((e) => setError(e.message));
    };
    const useLink = () => {
        setError(null);
        api.resolve(link).then((c) => { setFound({ label: 'From the link', cards: [c] }); setPicked(c); setKind(c.kind); })
            .catch((e) => setError(e.message));
    };
    const choose = () => {
        if (!picked)
            return;
        setError(null);
        api.choose(item.id, { kind: picked.kind, tmdbId: picked.tmdbId }, picked.kind === 'tv' && remember)
            .then((i) => onChosen(i, `${picked.title}${picked.year ? ` (${picked.year})` : ''}`))
            .catch((e) => setError(e.message));
    };
    return (_jsxs("section", { className: "panel wide question", "aria-labelledby": "q-h", children: [_jsx("h2", { id: "q-h", children: kind === 'tv' ? 'Which show is this?' : 'Which film is this?' }), found ? (_jsxs("p", { className: "hint", children: [found.label, " \u00B7 ", _jsx("button", { type: "button", className: "btn-link", onClick: () => { setFound(null); setPicked(null); }, children: "Back to muthur\u2019s suggestions" })] })) : null, cards.length > 0 ? (_jsx("div", { className: "cards", children: cards.map((c) => _jsx(TitleCard, { card: c, pressed: picked?.tmdbId === c.tmdbId && picked.kind === c.kind, onPick: () => setPicked(c) }, `${c.kind}${c.tmdbId}`)) })) : _jsx("p", { className: "hint", children: found ? 'Nothing found. Try another spelling, or leave the year out.' : 'muthur found nothing by this name. Search below.' }), _jsxs("div", { className: "subq", children: [_jsx("h3", { children: "Not there?" }), _jsxs("form", { className: "inline", onSubmit: (e) => { e.preventDefault(); search(); }, children: [_jsxs("div", { className: "seg", role: "group", "aria-label": "Search for", children: [_jsx("button", { type: "button", "aria-pressed": kind === 'tv', onClick: () => setKind('tv'), children: "Show" }), _jsx("button", { type: "button", "aria-pressed": kind === 'movie', onClick: () => setKind('movie'), children: "Film" })] }), _jsx("input", { className: "field", "aria-label": "Title", value: query, onChange: (e) => setQuery(e.target.value) }), _jsx("input", { className: "field year", "aria-label": "Year", inputMode: "numeric", placeholder: "Year", value: year, onChange: (e) => setYear(e.target.value.replace(/\D/g, '').slice(0, 4)) }), _jsx("button", { className: "btn btn-secondary btn-sm", type: "submit", disabled: !query.trim(), children: "Search TMDB" })] }), _jsxs("form", { className: "inline", onSubmit: (e) => { e.preventDefault(); useLink(); }, children: [_jsx("input", { className: "field", "aria-label": "A TMDB or IMDb link", placeholder: "Or paste a TMDB or IMDb link", value: link, onChange: (e) => setLink(e.target.value) }), _jsx("button", { className: "btn btn-secondary btn-sm", type: "submit", disabled: !link.trim(), children: "Use this link" })] })] }), picked?.kind === 'tv' && item.parsed?.title && (_jsxs("label", { className: "choice", children: [_jsx("input", { type: "checkbox", checked: remember, onChange: (e) => setRemember(e.target.checked) }), _jsxs("span", { children: ["Remember this for the show: the next download named \u201C", item.parsed.title, "\u201D goes straight to ", picked.title, "."] })] })), error && _jsx("div", { className: "banner banner-error", role: "alert", children: error }), _jsx("div", { className: "actions", style: { justifyContent: 'flex-end' }, children: picked ? (_jsxs("button", { className: "btn btn-primary", type: "button", disabled: busy, "aria-busy": busy, onClick: choose, children: ["It\u2019s ", picked.title, picked.year ? ` (${picked.year})` : ''] })) : (_jsx("button", { className: "btn btn-primary", type: "button", "aria-disabled": "true", title: "Choose one of the titles first", children: "Choose a title above" })) })] }));
}
// ---- Which episode is this? ---------------------------------------------------------------
const PROBLEM = {
    missing: (f) => `TMDB has no ${code(f.season ?? 0, f.episodes ?? [])} for this show.`,
    'other-episode': (f) => `The name says “${f.parsed?.episodeTitle}”, but TMDB’s ${code(f.season ?? 0, f.episodes ?? [])} is “${f.title}”.`,
    unnumbered: () => 'The episode number in the name is damaged or missing.',
    absolute: (f) => `Numbered ${f.parsed?.episodes[0] ?? '?'} without a season; muthur reads it as ${code(f.season ?? 0, f.episodes ?? [])}${f.title ? ` “${f.title}”` : ''}. Check it once.`,
    exists: (f) => `Your library already has ${code(f.season ?? 0, f.episodes ?? [])} in this season.`,
};
function startChoice(f) {
    const s = f.suggestion;
    const p = f.parsed;
    return {
        season: s?.season ?? f.tmdb_season ?? p?.season ?? 1,
        episode: s?.episode ?? f.tmdb_episode ?? p?.episodes[0] ?? 1,
        part: s?.part ?? p?.part ?? null,
        number: p?.episodes.length && !p.damaged && f.problem !== 'absolute' ? 'file' : 'tmdb',
    };
}
function EpisodeQuestion({ item, busy, onChosen, onWrongShow }) {
    const open = item.files.filter((f) => f.problem);
    const [map, setMap] = useState(() => Object.fromEntries(open.map((f) => [f.source, startChoice(f)])));
    const [seasons, setSeasons] = useState({});
    const [preview, setPreview] = useState(null);
    const [error, setError] = useState(null);
    const tmdbId = item.tmdb_id ?? 0;
    const wanted = [...new Set(Object.values(map).map((c) => c.season))];
    useEffect(() => {
        wanted.filter((s) => !seasons[s]).forEach((s) => {
            api.season(tmdbId, s).then((d) => setSeasons((old) => ({ ...old, [s]: d }))).catch((e) => setError(e.message));
        });
    }, [wanted.join(','), tmdbId]); // eslint-disable-line react-hooks/exhaustive-deps
    const choice = { kind: 'tv', tmdbId, episodes: map };
    useEffect(() => {
        api.preview(item.id, choice).then(setPreview).catch((e) => setError(e.message));
    }, [JSON.stringify(map)]); // eslint-disable-line react-hooks/exhaustive-deps
    const set = (source, change) => setMap((m) => ({ ...m, [source]: { ...m[source], ...change } }));
    const planned = (source) => preview?.files.find((f) => f.source === source);
    const blocked = !preview || preview.files.some((f) => f.problem);
    const duplicate = preview?.files.some((f) => f.problem === 'exists');
    const one = open.length === 1 ? planned(open[0].source) : null;
    const label = one?.season != null && one.episodes ? `File it as ${code(one.season, one.episodes)}${one.title ? ` · ${one.title}` : ''}` : `File these ${open.length} episodes`;
    const choose = () => {
        setError(null);
        api.choose(item.id, choice, false).then((i) => onChosen(i, item.title ?? 'it')).catch((e) => setError(e.message));
    };
    return (_jsxs("section", { className: "panel wide question", "aria-labelledby": "q-h", children: [_jsx("h2", { id: "q-h", children: open.length === 1 ? 'Which episode is this?' : `Which episodes are these? (${open.length})` }), _jsxs("p", { className: "hint", children: [item.title, item.year ? ` (${item.year})` : '', " \u00B7 ", _jsx("button", { type: "button", className: "btn-link", onClick: onWrongShow, children: "Wrong show?" })] }), open.map((f) => {
                const c = map[f.source];
                const season = seasons[c.season];
                const p = planned(f.source);
                const own = f.parsed?.episodes.length && !f.parsed.damaged ? code(f.parsed.season ?? 0, f.parsed.episodes) : null;
                return (_jsxs("div", { className: "subq", children: [_jsx("span", { className: "mono small", title: f.source, style: { wordBreak: 'break-all' }, children: middle(f.source.split('/').pop() ?? f.source, 80) }), _jsx("p", { className: "hint", style: { color: 'var(--warn-text)' }, children: (PROBLEM[f.problem ?? ''] ?? (() => ''))(f) }), _jsxs("div", { className: "pair", children: [_jsxs("label", { className: "field-label", children: ["Season", _jsx("select", { className: "field", value: c.season, onChange: (e) => set(f.source, { season: Number(e.target.value), episode: 1 }), children: (season?.seasons ?? [{ season: c.season, name: null, episodes: 0 }]).map((s) => (_jsxs("option", { value: s.season, children: [s.name ?? `Season ${s.season}`, s.episodes ? ` · ${s.episodes} episodes` : ''] }, s.season))) })] }), _jsxs("label", { className: "field-label", children: ["Part of the episode", _jsxs("select", { className: "field", value: c.part ?? '', onChange: (e) => set(f.source, { part: e.target.value ? Number(e.target.value) : null }), children: [_jsx("option", { value: "", children: "The whole episode" }), [1, 2, 3].map((n) => _jsxs("option", { value: n, children: ["Part ", n] }, n))] })] })] }), _jsxs("label", { className: "field-label", children: ["The episode on TMDB", _jsx("select", { className: "field", value: c.episode, onChange: (e) => set(f.source, { episode: Number(e.target.value) }), children: (season?.episodes ?? []).map((e) => (_jsxs("option", { value: e.episode, children: [code(c.season, e.episode), " \u00B7 ", e.title ?? 'untitled', e.aired ? ` · ${aired(e.aired)}` : '', e.runtime ? ` · ${e.runtime} min` : ''] }, e.episode))) })] }), own && (_jsxs("fieldset", { style: { border: 0, padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 6 }, children: [_jsx("legend", { className: "small muted", style: { marginBottom: 6 }, children: "What number does the file get?" }), _jsxs("label", { className: "choice", children: [_jsx("input", { type: "radio", name: `n-${f.source}`, checked: c.number === 'file', onChange: () => set(f.source, { number: 'file' }) }), _jsxs("span", { children: [own, ", as the download numbers it ", _jsx("span", { className: "muted", children: "\u00B7 keeps the numbering your library already uses for this season" })] })] }), _jsxs("label", { className: "choice", children: [_jsx("input", { type: "radio", name: `n-${f.source}`, checked: c.number === 'tmdb', onChange: () => set(f.source, { number: 'tmdb' }) }), _jsxs("span", { children: [code(c.season, c.episode), ", as TMDB numbers it"] })] })] })), p?.target && (_jsxs("span", { className: "mono small", style: { wordBreak: 'break-all', color: p.problem ? 'var(--warn-text)' : 'var(--accent-text)' }, children: ["\u2192 TV/", p.target, p.problem ? ` · ${(PROBLEM[p.problem] ?? (() => ''))(p)}` : ''] }))] }, f.source));
            }), error && _jsx("div", { className: "banner banner-error", role: "alert", children: error }), _jsx("p", { className: "hint", children: duplicate
                    ? 'This episode is already in your library under that number. muthur never overwrites, so this copy stays in the downloads; compare the two and keep the one you want.'
                    : 'The NFO gets the plot, date and score of the TMDB episode you pick, under the file’s own number.' }), _jsx("div", { className: "actions", style: { justifyContent: 'flex-end' }, children: blocked ? (_jsx("button", { className: "btn btn-primary", type: "button", "aria-disabled": "true", title: "Pick an episode that fits first", children: !preview ? 'Checking…' : duplicate ? 'Already in your library' : 'Pick an episode that fits' })) : (_jsx("button", { className: "btn btn-primary", type: "button", disabled: busy, "aria-busy": busy, onClick: choose, children: label })) })] }));
}
// ---- What the name says ------------------------------------------------------------------------
function FromTheName({ item, onForget }) {
    return (_jsxs("aside", { className: "panel narrow", "aria-label": "Read from the name", style: { display: 'flex', flexDirection: 'column', gap: 12 }, children: [_jsxs("div", { children: [_jsx("p", { className: "eyebrow", children: "Read from the name" }), _jsx("span", { className: "mono small", title: item.id, style: { wordBreak: 'break-all' }, children: middle(splitId(item.id).name, 90) }), splitId(item.id).folder && _jsxs("span", { className: "small muted", children: [" \u00B7 in ", splitId(item.id).folder] })] }), _jsxs("ul", { className: "rows", children: [_jsxs("li", { children: [_jsx("span", { className: "muted", children: "Title" }), _jsx("span", { children: item.parsed?.title ?? '—' })] }), _jsxs("li", { children: [_jsx("span", { className: "muted", children: "Year" }), _jsx("span", { children: item.parsed?.year ?? '—' })] }), item.kind === 'tv' && item.files.slice(0, 6).map((f) => (_jsxs("li", { children: [_jsx("span", { className: "muted", children: "Episode" }), _jsxs("span", { children: [f.parsed?.damaged ? 'damaged number' : f.parsed?.episodes.length ? code(f.parsed.season ?? 0, f.parsed.episodes) : '—', f.parsed?.episodeTitle ? ` · ${f.parsed.episodeTitle}` : '', f.parsed?.part ? ` · part ${f.parsed.part}` : ''] })] }, f.source)))] }), _jsxs("p", { className: "status small", children: [_jsx(Dot, { kind: "dot-warning" }), item.reason] }), item.notes.map((n) => _jsx("p", { className: "hint", children: n }, n)), item.chosen && _jsx("button", { type: "button", className: "btn-link", style: { alignSelf: 'flex-start' }, onClick: onForget, children: "Forget my choice" })] }));
}
export function ReviewPage({ status, refresh }) {
    const [items, setItems] = useState(null);
    const [index, setIndex] = useState(0);
    const [askShow, setAskShow] = useState(false);
    const [done, setDone] = useState(null);
    const [error, setError] = useState(null);
    const running = Boolean(status?.job?.running);
    useEffect(() => {
        api.inbox().then((d) => setItems(d.items.filter((i) => i.status === 'review'))).catch((e) => setError(e.message));
    }, [status?.inbox.scannedAt, running]);
    const current = items?.[Math.min(index, (items?.length ?? 1) - 1)] ?? null;
    const go = useCallback((step) => {
        setAskShow(false);
        setDone(null);
        setIndex((i) => Math.max(0, Math.min((items?.length ?? 1) - 1, i + step)));
    }, [items?.length]);
    useEffect(() => {
        const onKey = (e) => {
            const t = e.target;
            if (t.closest('input, select, textarea') || e.altKey || e.ctrlKey || e.metaKey)
                return;
            if (e.key === 'ArrowRight' || e.key === 'j')
                go(1);
            if (e.key === 'ArrowLeft' || e.key === 'k')
                go(-1);
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [go]);
    const chosen = (i, what) => {
        setAskShow(false);
        window.scrollTo(0, 0); // the result shows at the top, with the next item under it
        if (i.status === 'ready') {
            setItems((list) => (list ?? []).filter((x) => x.id !== i.id));
            setDone(`${what} is ready. It moves with the next Apply in the Inbox.`);
        }
        else {
            setItems((list) => (list ?? []).map((x) => (x.id === i.id ? i : x)));
        }
        refresh();
    };
    const forget = (id) => {
        api.forget(id).then((i) => { setItems((list) => (list ?? []).map((x) => (x.id === id ? i : x))); refresh(); })
            .catch((e) => setError(e.message));
    };
    const identity = current && (askShow || current.tmdb_id == null || (!current.known && !current.chosen && current.candidates.length > 0 && !current.files.some((f) => f.problem)));
    const episodes = current && !identity && current.kind === 'tv' && current.files.some((f) => f.problem);
    return (_jsxs("div", { className: "page", children: [_jsxs("header", { className: "page-head", children: [_jsxs("div", { children: [_jsx("p", { className: "eyebrow", children: "Needs you" }), _jsx("h1", { children: "Review" }), items && items.length > 0 && _jsxs("p", { className: "lede", children: [items.length, " to decide"] })] }), items && items.length > 1 && (_jsxs("div", { className: "actions", children: [_jsx("button", { className: "btn btn-ghost btn-sm", type: "button", onClick: () => go(-1), disabled: index === 0, "aria-keyshortcuts": "ArrowLeft", children: "\u2190 Previous" }), _jsxs("span", { className: "small muted num", children: [Math.min(index, items.length - 1) + 1, " of ", items.length] }), _jsx("button", { className: "btn btn-ghost btn-sm", type: "button", onClick: () => go(1), disabled: index >= items.length - 1, "aria-keyshortcuts": "ArrowRight", children: "Next \u2192" }), _jsx("span", { className: "small muted", children: "Keys: \u2190 \u2192 or j k" })] }))] }), _jsx(JobError, { job: status?.job }), !items && !error && _jsx(Loading, { label: "Loading what needs you" }), error && _jsx("div", { className: "banner banner-error", role: "alert", children: error }), done && (_jsxs("div", { className: "banner banner-note", role: "status", children: [_jsxs("span", { className: "status", children: [_jsx(Dot, { kind: "dot-success" }), done] }), _jsx(Link, { to: "/inbox?show=ready", children: "Open the Inbox" })] })), items && items.length === 0 && (_jsxs("section", { className: "panel", style: { textAlign: 'center', padding: '40px 16px' }, children: [_jsx("h2", { style: { margin: '0 0 6px', fontSize: '1.2rem' }, children: "Nothing to review" }), _jsx("p", { className: "hint", children: "Nothing needs you." })] })), current && (_jsxs("div", { className: "split", children: [identity ? _jsx(IdentityQuestion, { item: current, busy: running, onChosen: chosen })
                        : episodes ? _jsx(EpisodeQuestion, { item: current, busy: running, onChosen: chosen, onWrongShow: () => setAskShow(true) })
                            : (_jsxs("section", { className: "panel wide question", children: [_jsx("h2", { children: "Not ready yet" }), _jsx("p", { className: "hint", children: current.reason }), _jsx("div", { className: "actions", children: _jsx("button", { className: "btn btn-secondary btn-sm", type: "button", onClick: () => setAskShow(true), children: "Choose the show or film again" }) })] })), _jsx(FromTheName, { item: current, onForget: () => forget(current.id) })] }, current.id))] }));
}
