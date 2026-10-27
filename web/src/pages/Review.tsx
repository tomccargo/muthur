import { useCallback, useEffect, useMemo, useState, type CSSProperties } from 'react';
import { api, type Card, type Choice, type EpisodeChoice, type Item, type Kind, type Planned, type Season } from '../api';
import type { StatusHook } from '../App';
import { ClearField, Dot, JobError, Loading } from '../components';
import { SIGNALS, hue, middle, splitId } from '../labels';
import { Link } from '../nav';

const IMAGES = 'https://image.tmdb.org/t/p/w185';
const code = (s: number, e: number[] | number) => `S${String(s).padStart(2, '0')}${(Array.isArray(e) ? e : [e]).map((n) => `E${String(n).padStart(2, '0')}`).join('')}`;
const aired = (d: string | null) => (d ? new Date(d).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }) : '');

// A missing poster gets the title's initials on the title's own tint (DESIGN.md §8), never a broken image.
export function Poster({ path, title }: { path: string | null | undefined; title: string }) {
  const [failed, setFailed] = useState(false);
  if (!path || failed) {
    const initials = title.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join('').toUpperCase();
    return <span className="poster" style={{ '--hue': hue(title) } as CSSProperties} aria-hidden="true"><span className="poster-initials">{initials || '?'}</span></span>;
  }
  return <img className="poster" src={IMAGES + path} alt="" loading="lazy" onError={() => setFailed(true)} />;
}

export function TitleCard({ card, pressed, onPick }: { card: Card; pressed: boolean; onPick: () => void }) {
  const why = Object.entries(card.signals ?? {}).filter(([k]) => k !== 'popularity').map(([k, v]) => `${SIGNALS[k] ?? k} ${Math.round(v * 100)}%`);
  return (
    <button type="button" className="card" aria-pressed={pressed} onClick={onPick}>
      <Poster path={card.poster} title={card.title} />
      <span style={{ display: 'flex', flexDirection: 'column', gap: 3, minWidth: 0 }}>
        <strong style={{ overflowWrap: 'anywhere' }}>{card.title}{card.year ? ` (${card.year})` : ''}</strong>
        {card.originalTitle && card.originalTitle !== card.title && <span className="small muted">{card.originalTitle}</span>}
        {card.overview && <span className="small clamp">{card.overview}</span>}
        {why.length > 0 && <span className="small muted">{why.join(' · ')}</span>}
      </span>
    </button>
  );
}

// ---- Which show or film is this? -------------------------------------------------------------
function IdentityQuestion({ item, busy, onChosen }: { item: Item; busy: boolean; onChosen: (i: Item, note: string) => void }) {
  const suggested = useMemo<Card[]>(() => item.candidates.map((c) => ({
    kind: (item.kind ?? 'movie') as Kind, tmdbId: c.tmdbId, title: c.title, originalTitle: c.originalTitle, year: c.year,
    overview: c.overview ?? '', poster: c.poster ?? null, signals: c.signals,
  })), [item]);
  const [kind, setKind] = useState<Kind>((item.kind ?? 'movie') as Kind);
  const [query, setQuery] = useState(item.parsed?.title ?? splitId(item.id).name);
  const [year, setYear] = useState(item.parsed?.year ? String(item.parsed.year) : '');
  const [link, setLink] = useState('');
  const [found, setFound] = useState<{ label: string; cards: Card[] } | null>(null);
  const [picked, setPicked] = useState<Card | null>(null);
  const [remember, setRemember] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const cards = found?.cards ?? suggested;

  const search = () => {
    setError(null);
    api.search(kind, query, year ? Number(year) : undefined)
      .then((r) => { setFound({ label: `Results for “${query}”${year ? ` (${year})` : ''}`, cards: r.results }); setPicked(null); })
      .catch((e: Error) => setError(e.message));
  };
  const useLink = () => {
    setError(null);
    api.resolve(link).then((c) => { setFound({ label: 'From the link', cards: [c] }); setPicked(c); setKind(c.kind); })
      .catch((e: Error) => setError(e.message));
  };
  const choose = () => {
    if (!picked) return;
    setError(null);
    api.choose(item.id, { kind: picked.kind, tmdbId: picked.tmdbId }, picked.kind === 'tv' && remember)
      .then((i) => onChosen(i, `${picked.title}${picked.year ? ` (${picked.year})` : ''}`))
      .catch((e: Error) => setError(e.message));
  };

  return (
    <section className="panel wide question" aria-labelledby="q-h">
      <h2 id="q-h">{kind === 'tv' ? 'Which show is this?' : 'Which film is this?'}</h2>
      {found ? (
        <p className="hint">{found.label} · <button type="button" className="btn-link" onClick={() => { setFound(null); setPicked(null); }}>Back to muthur’s suggestions</button></p>
      ) : null}
      {cards.length > 0 ? (
        <div className="cards">
          {cards.map((c) => <TitleCard key={`${c.kind}${c.tmdbId}`} card={c} pressed={picked?.tmdbId === c.tmdbId && picked.kind === c.kind} onPick={() => setPicked(c)} />)}
        </div>
      ) : <p className="hint">{found ? 'Nothing found. Try another spelling, or leave the year out.' : 'muthur found nothing by this name. Search below.'}</p>}

      <div className="subq">
        <h3>Not there?</h3>
        <form className="inline" onSubmit={(e) => { e.preventDefault(); search(); }}>
          <div className="seg" role="group" aria-label="Search for">
            <button type="button" aria-pressed={kind === 'tv'} onClick={() => setKind('tv')}>Show</button>
            <button type="button" aria-pressed={kind === 'movie'} onClick={() => setKind('movie')}>Film</button>
          </div>
          <ClearField aria-label="Title" value={query} onChange={setQuery} />
          <input className="field year" aria-label="Year" inputMode="numeric" placeholder="Year" value={year} onChange={(e) => setYear(e.target.value.replace(/\D/g, '').slice(0, 4))} />
          <button className="btn btn-secondary btn-sm" type="submit" disabled={!query.trim()}>Search TMDB</button>
        </form>
        <form className="inline" onSubmit={(e) => { e.preventDefault(); useLink(); }}>
          <ClearField aria-label="A TMDB or IMDb link" placeholder="Or paste a TMDB or IMDb link" value={link} onChange={setLink} />
          <button className="btn btn-secondary btn-sm" type="submit" disabled={!link.trim()}>Use this link</button>
        </form>
      </div>

      {picked?.kind === 'tv' && item.parsed?.title && (
        <label className="choice">
          <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
          <span>Remember this for the show: the next download named “{item.parsed.title}” goes straight to {picked.title}.</span>
        </label>
      )}
      {error && <div className="banner banner-error" role="alert">{error}</div>}
      <div className="actions" style={{ justifyContent: 'flex-end' }}>
        {picked ? (
          <button className="btn btn-primary" type="button" disabled={busy} aria-busy={busy} onClick={choose}>It’s {picked.title}{picked.year ? ` (${picked.year})` : ''}</button>
        ) : (
          <button className="btn btn-primary" type="button" aria-disabled="true" title="Choose one of the titles first">Choose a title above</button>
        )}
      </div>
    </section>
  );
}

// ---- Which episode is this? ---------------------------------------------------------------
const PROBLEM: Record<string, (f: Planned) => string> = {
  missing: (f) => `TMDB has no ${code(f.season ?? 0, f.episodes ?? [])} for this show.`,
  'other-episode': (f) => `The name says “${f.parsed?.episodeTitle}”, but TMDB’s ${code(f.season ?? 0, f.episodes ?? [])} is “${f.title}”.`,
  unnumbered: () => 'The episode number in the name is damaged or missing.',
  absolute: (f) => `Numbered ${f.parsed?.episodes[0] ?? '?'} without a season; muthur reads it as ${code(f.season ?? 0, f.episodes ?? [])}${f.title ? ` “${f.title}”` : ''}. Check it once.`,
  exists: (f) => `Your library already has ${code(f.season ?? 0, f.episodes ?? [])} in this season.`,
};

function startChoice(f: Planned): EpisodeChoice {
  const s = f.suggestion;
  const p = f.parsed;
  return {
    season: s?.season ?? f.tmdb_season ?? p?.season ?? 1,
    episode: s?.episode ?? f.tmdb_episode ?? p?.episodes[0] ?? 1,
    part: s?.part ?? p?.part ?? null,
    number: p?.episodes.length && !p.damaged && f.problem !== 'absolute' ? 'file' : 'tmdb',
  };
}

function EpisodeQuestion({ item, busy, onChosen, onWrongShow }: { item: Item; busy: boolean; onChosen: (i: Item, note: string) => void; onWrongShow: () => void }) {
  const open = item.files.filter((f) => f.problem);
  const [map, setMap] = useState<Record<string, EpisodeChoice>>(() => Object.fromEntries(open.map((f) => [f.source, startChoice(f)])));
  const [seasons, setSeasons] = useState<Record<number, Season>>({});
  const [preview, setPreview] = useState<Item | null>(null);
  const [error, setError] = useState<string | null>(null);
  const tmdbId = item.tmdb_id ?? 0;

  const wanted = [...new Set(Object.values(map).map((c) => c.season))];
  useEffect(() => {
    wanted.filter((s) => !seasons[s]).forEach((s) => {
      api.season(tmdbId, s).then((d) => setSeasons((old) => ({ ...old, [s]: d }))).catch((e: Error) => setError(e.message));
    });
  }, [wanted.join(','), tmdbId]); // eslint-disable-line react-hooks/exhaustive-deps

  const choice: Choice = { kind: 'tv', tmdbId, episodes: map };
  useEffect(() => {
    api.preview(item.id, choice).then(setPreview).catch((e: Error) => setError(e.message));
  }, [JSON.stringify(map)]); // eslint-disable-line react-hooks/exhaustive-deps

  const set = (source: string, change: Partial<EpisodeChoice>) => setMap((m) => ({ ...m, [source]: { ...m[source], ...change } }));
  const planned = (source: string) => preview?.files.find((f) => f.source === source);
  const blocked = !preview || preview.files.some((f) => f.problem);
  const duplicate = preview?.files.some((f) => f.problem === 'exists');
  const one = open.length === 1 ? planned(open[0].source) : null;
  const label = one?.season != null && one.episodes ? `File it as ${code(one.season, one.episodes)}${one.title ? ` · ${one.title}` : ''}` : `File these ${open.length} episodes`;

  const choose = () => {
    setError(null);
    api.choose(item.id, choice, false).then((i) => onChosen(i, item.title ?? 'it')).catch((e: Error) => setError(e.message));
  };

  return (
    <section className="panel wide question" aria-labelledby="q-h">
      <h2 id="q-h">{open.length === 1 ? 'Which episode is this?' : `Which episodes are these? (${open.length})`}</h2>
      <p className="hint">
        {item.title}{item.year ? ` (${item.year})` : ''} · <button type="button" className="btn-link" onClick={onWrongShow}>Wrong show?</button>
      </p>
      {open.map((f) => {
        const c = map[f.source];
        const season = seasons[c.season];
        const p = planned(f.source);
        const own = f.parsed?.episodes.length && !f.parsed.damaged ? code(f.parsed.season ?? 0, f.parsed.episodes) : null;
        return (
          <div key={f.source} className="subq">
            <span className="mono small" title={f.source} style={{ wordBreak: 'break-all' }}>{middle(f.source.split('/').pop() ?? f.source, 80)}</span>
            <p className="hint" style={{ color: 'var(--warn-text)' }}>{(PROBLEM[f.problem ?? ''] ?? (() => ''))(f)}</p>
            <div className="pair">
              <label className="field-label">Season
                <select className="field" value={c.season} onChange={(e) => set(f.source, { season: Number(e.target.value), episode: 1 })}>
                  {(season?.seasons ?? [{ season: c.season, name: null, episodes: 0 }]).map((s) => (
                    <option key={s.season} value={s.season}>{s.name ?? `Season ${s.season}`}{s.episodes ? ` · ${s.episodes} episodes` : ''}</option>
                  ))}
                </select>
              </label>
              <label className="field-label">Part of the episode
                <select className="field" value={c.part ?? ''} onChange={(e) => set(f.source, { part: e.target.value ? Number(e.target.value) : null })}>
                  <option value="">The whole episode</option>
                  {[1, 2, 3].map((n) => <option key={n} value={n}>Part {n}</option>)}
                </select>
              </label>
            </div>
            <label className="field-label">The episode on TMDB
              <select className="field" value={c.episode} onChange={(e) => set(f.source, { episode: Number(e.target.value) })}>
                {(season?.episodes ?? []).map((e) => (
                  <option key={e.episode} value={e.episode}>
                    {code(c.season, e.episode)} · {e.title ?? 'untitled'}{e.aired ? ` · ${aired(e.aired)}` : ''}{e.runtime ? ` · ${e.runtime} min` : ''}
                  </option>
                ))}
              </select>
            </label>
            {own && (
              <fieldset style={{ border: 0, padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
                <legend className="small muted" style={{ marginBottom: 6 }}>What number does the file get?</legend>
                <label className="choice">
                  <input type="radio" name={`n-${f.source}`} checked={c.number === 'file'} onChange={() => set(f.source, { number: 'file' })} />
                  <span>{own}, as the download numbers it <span className="muted">· keeps the numbering your library already uses for this season</span></span>
                </label>
                <label className="choice">
                  <input type="radio" name={`n-${f.source}`} checked={c.number === 'tmdb'} onChange={() => set(f.source, { number: 'tmdb' })} />
                  <span>{code(c.season, c.episode)}, as TMDB numbers it</span>
                </label>
              </fieldset>
            )}
            {p?.target && (
              <span className="mono small" style={{ wordBreak: 'break-all', color: p.problem ? 'var(--warn-text)' : 'var(--accent-text)' }}>
                → TV/{p.target}{p.problem ? ` · ${(PROBLEM[p.problem] ?? (() => ''))(p)}` : ''}
              </span>
            )}
          </div>
        );
      })}
      {error && <div className="banner banner-error" role="alert">{error}</div>}
      <p className="hint">
        {duplicate
          ? 'This episode is already in your library under that number. muthur never overwrites, so this copy stays in the downloads; compare the two and keep the one you want.'
          : 'The NFO gets the plot, date and score of the TMDB episode you pick, under the file’s own number.'}
      </p>
      <div className="actions" style={{ justifyContent: 'flex-end' }}>
        {blocked ? (
          <button className="btn btn-primary" type="button" aria-disabled="true" title="Pick an episode that fits first">
            {!preview ? 'Checking…' : duplicate ? 'Already in your library' : 'Pick an episode that fits'}
          </button>
        ) : (
          <button className="btn btn-primary" type="button" disabled={busy} aria-busy={busy} onClick={choose}>{label}</button>
        )}
      </div>
    </section>
  );
}

// ---- What the name says ------------------------------------------------------------------------
function FromTheName({ item, onForget }: { item: Item; onForget: () => void }) {
  return (
    <aside className="panel narrow" aria-label="Read from the name" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div>
        <p className="eyebrow">Read from the name</p>
        <span className="mono small" title={item.id} style={{ wordBreak: 'break-all' }}>{middle(splitId(item.id).name, 90)}</span>
        {splitId(item.id).folder && <span className="small muted"> · in {splitId(item.id).folder}</span>}
      </div>
      <ul className="rows">
        <li><span className="muted">Title</span><span>{item.parsed?.title ?? '—'}</span></li>
        <li><span className="muted">Year</span><span>{item.parsed?.year ?? '—'}</span></li>
        {item.kind === 'tv' && item.files.slice(0, 6).map((f) => (
          <li key={f.source}>
            <span className="muted">Episode</span>
            <span>
              {f.parsed?.damaged ? 'damaged number' : f.parsed?.episodes.length ? code(f.parsed.season ?? 0, f.parsed.episodes) : '—'}
              {f.parsed?.episodeTitle ? ` · ${f.parsed.episodeTitle}` : ''}{f.parsed?.part ? ` · part ${f.parsed.part}` : ''}
            </span>
          </li>
        ))}
      </ul>
      <p className="status small"><Dot kind="dot-warning" />{item.reason}</p>
      {item.notes.map((n) => <p key={n} className="hint">{n}</p>)}
      {item.chosen && <button type="button" className="btn-link" style={{ alignSelf: 'flex-start' }} onClick={onForget}>Forget my choice</button>}
    </aside>
  );
}

export function ReviewPage({ status, refresh }: StatusHook) {
  const [items, setItems] = useState<Item[] | null>(null);
  const [index, setIndex] = useState(0);
  const [askShow, setAskShow] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const running = Boolean(status?.job?.running);

  useEffect(() => {
    api.inbox().then((d) => setItems(d.items.filter((i) => i.status === 'review'))).catch((e: Error) => setError(e.message));
  }, [status?.inbox.scannedAt, running]);

  const current = items?.[Math.min(index, (items?.length ?? 1) - 1)] ?? null;
  const go = useCallback((step: number) => {
    setAskShow(false);
    setDone(null);
    setIndex((i) => Math.max(0, Math.min((items?.length ?? 1) - 1, i + step)));
  }, [items?.length]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.closest('input, select, textarea') || e.altKey || e.ctrlKey || e.metaKey) return;
      if (e.key === 'ArrowRight' || e.key === 'j') go(1);
      if (e.key === 'ArrowLeft' || e.key === 'k') go(-1);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [go]);

  const chosen = (i: Item, what: string) => {
    setAskShow(false);
    window.scrollTo(0, 0); // the result shows at the top, with the next item under it
    if (i.status === 'ready') {
      setItems((list) => (list ?? []).filter((x) => x.id !== i.id));
      setDone(`${what} is ready. It moves with the next Apply in the Inbox.`);
    } else {
      setItems((list) => (list ?? []).map((x) => (x.id === i.id ? i : x)));
    }
    refresh();
  };
  const forget = (id: string) => {
    api.forget(id).then((i) => { setItems((list) => (list ?? []).map((x) => (x.id === id ? i : x))); refresh(); })
      .catch((e: Error) => setError(e.message));
  };

  const identity = current && (askShow || current.tmdb_id == null || (!current.known && !current.chosen && current.candidates.length > 0 && !current.files.some((f) => f.problem)));
  const episodes = current && !identity && current.kind === 'tv' && current.files.some((f) => f.problem);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">Needs you</p>
          <h1>Review</h1>
          {items && items.length > 0 && <p className="lede">{items.length} to decide</p>}
        </div>
        {items && items.length > 1 && (
          <div className="actions">
            <button className="btn btn-ghost btn-sm" type="button" onClick={() => go(-1)} disabled={index === 0} aria-keyshortcuts="ArrowLeft">← Previous</button>
            <span className="small muted num">{Math.min(index, items.length - 1) + 1} of {items.length}</span>
            <button className="btn btn-ghost btn-sm" type="button" onClick={() => go(1)} disabled={index >= items.length - 1} aria-keyshortcuts="ArrowRight">Next →</button>
            <span className="small muted">Keys: ← → or j k</span>
          </div>
        )}
      </header>
      <JobError job={status?.job} />
      {!items && !error && <Loading label="Loading what needs you" />}
      {error && <div className="banner banner-error" role="alert">{error}</div>}
      {done && (
        <div className="banner banner-note" role="status">
          <span className="status"><Dot kind="dot-success" />{done}</span>
          <Link to="/inbox?show=ready">Open the Inbox</Link>
        </div>
      )}
      {items && items.length === 0 && (
        <section className="panel" style={{ textAlign: 'center', padding: '40px 16px' }}>
          <h2 style={{ margin: '0 0 6px', fontSize: '1.2rem' }}>Nothing to review</h2>
          <p className="hint">Nothing needs you.</p>
        </section>
      )}
      {current && (
        <div className="split" key={current.id}>
          {identity ? <IdentityQuestion item={current} busy={running} onChosen={chosen} />
            : episodes ? <EpisodeQuestion item={current} busy={running} onChosen={chosen} onWrongShow={() => setAskShow(true)} />
              : (
                <section className="panel wide question">
                  <h2>Not ready yet</h2>
                  <p className="hint">{current.reason}</p>
                  <div className="actions"><button className="btn btn-secondary btn-sm" type="button" onClick={() => setAskShow(true)}>Choose the show or film again</button></div>
                </section>
              )}
          <FromTheName item={current} onForget={() => forget(current.id)} />
        </div>
      )}
    </div>
  );
}
