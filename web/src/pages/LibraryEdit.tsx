import { useState } from 'react';
import { api, type Card, type Kind } from '../api';
import { TitleCard } from './Review';

const IMAGES = 'https://image.tmdb.org/t/p/w185';
type Mode = null | 'match' | 'title' | 'poster';

// Change a show's or film's match, title or poster (DESIGN.md §13). Each change is a run History can put back.
export function LibraryEditor({ kind, path, nfo, posterTarget, tmdbId, title, onDone }: {
  kind: Kind; path: string; nfo: string | null; posterTarget: string; tmdbId: number | null; title: string; onDone: (text: string) => void;
}) {
  const [mode, setMode] = useState<Mode>(null);
  const [query, setQuery] = useState(title);
  const [cards, setCards] = useState<Card[] | null>(null);
  const [picked, setPicked] = useState<Card | null>(null);
  const [newTitle, setNewTitle] = useState(title);
  const [posters, setPosters] = useState<{ path: string; language: string | null }[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = (p: Promise<{ label: string }>) => {
    setBusy(true);
    setError(null);
    p.then((r) => { setMode(null); onDone(`${r.label}. It can be put back from History.`); })
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false));
  };
  const open = (m: Mode) => {
    setMode(mode === m ? null : m);
    setError(null);
    if (m === 'poster' && tmdbId && !posters) api.libraryPosters(kind, tmdbId).then((r) => setPosters(r.posters)).catch((e: Error) => setError(e.message));
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div className="actions">
        <button className="btn btn-secondary btn-sm" type="button" aria-expanded={mode === 'match'} onClick={() => open('match')}>Change the match…</button>
        {nfo && <button className="btn btn-secondary btn-sm" type="button" aria-expanded={mode === 'title'} onClick={() => open('title')}>Change the title…</button>}
        {tmdbId && <button className="btn btn-secondary btn-sm" type="button" aria-expanded={mode === 'poster'} onClick={() => open('poster')}>Choose a poster…</button>}
      </div>
      {mode === 'match' && (
        <section className="panel question" aria-label="Change the match">
          <p className="hint">Which {kind === 'tv' ? 'show' : 'film'} is this? muthur writes its NFO and artwork from the one you pick; the old files are kept for putting back.</p>
          <form className="inline" onSubmit={(e) => { e.preventDefault(); api.search(kind, query).then((r) => { setCards(r.results); setPicked(null); }).catch((x: Error) => setError(x.message)); }}>
            <input className="field" aria-label="Title" value={query} onChange={(e) => setQuery(e.target.value)} />
            <button className="btn btn-secondary btn-sm" type="submit" disabled={!query.trim()}>Search TMDB</button>
          </form>
          {cards && (cards.length
            ? <div className="cards">{cards.slice(0, 9).map((c) => <TitleCard key={c.tmdbId} card={c} pressed={picked?.tmdbId === c.tmdbId} onPick={() => setPicked(c)} />)}</div>
            : <p className="hint">Nothing found; try another spelling.</p>)}
          {picked && (
            <button className="btn btn-secondary btn-sm" type="button" disabled={busy} style={{ alignSelf: 'flex-start' }}
              aria-busy={busy} onClick={() => run(api.libraryMatch(kind, path, picked.tmdbId))}>It’s {picked.title}{picked.year ? ` (${picked.year})` : ''}</button>
          )}
        </section>
      )}
      {mode === 'title' && nfo && (
        <section className="panel question" aria-label="Change the title">
          <form className="inline" onSubmit={(e) => { e.preventDefault(); run(api.libraryTitle(nfo, newTitle)); }}>
            <input className="field" aria-label="Title" value={newTitle} onChange={(e) => setNewTitle(e.target.value)} />
            <button className="btn btn-secondary btn-sm" type="submit" disabled={busy || !newTitle.trim() || newTitle === title} aria-busy={busy}>Save the title</button>
          </form>
          <p className="hint">Only the title in the NFO changes; Kodi shows it after re-reading the item.</p>
        </section>
      )}
      {mode === 'poster' && (
        <section className="panel question" aria-label="Choose a poster">
          {!posters ? <p className="hint">Loading TMDB’s posters…</p> : posters.length === 0 ? <p className="hint">TMDB has no posters for this.</p> : (
            <div className="posters">
              {posters.map((p) => (
                <button key={p.path} type="button" className="poster-tile" style={{ border: 0, background: 'none', padding: 0, cursor: 'pointer' }}
                  disabled={busy} onClick={() => run(api.libraryPoster(posterTarget, p.path))} aria-label={`Use this poster${p.language ? ` (${p.language})` : ''}`}>
                  <img className="poster" src={IMAGES + p.path} alt="" loading="lazy" />
                  <span className="small muted">{p.language ?? 'no text'}</span>
                </button>
              ))}
            </div>
          )}
        </section>
      )}
      {error && <div className="banner banner-error" role="alert">{error}</div>}
    </div>
  );
}
