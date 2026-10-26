import { useEffect, useMemo, useState } from 'react';
import { api, type Film, type LibEpisode, type LibProblems, type Library, type ShowDetail, type ShowSummary } from '../api';
import type { StatusHook } from '../App';
import { Dot, JobError, Loading } from '../components';
import { middle, score, size, when } from '../labels';
import { Link, navigate, useLocation } from '../nav';
import { LibraryEditor } from './LibraryEdit';
import { hero, heroClick, heroLanded, motionOn } from '../motion';

// The page a poster was clicked for: its cover takes over the flying poster (motion.ts).
const isFlying = () => motionOn() && hero.to === location.pathname + location.search;
// A film's own folder: where its video is, which may be a folder deeper than the film's top folder.
const filmDir = (f: Film) => (f.file && f.file.includes('/') ? f.file.split('/').slice(0, -1).join('/') : f.key);

type Filter = 'all' | keyof LibProblems;
// Each problem filter says where it's fixed.
const FIX_HINT: Partial<Record<Filter, [string, string, string]>> = {
  noNfo: ['Health writes the missing NFOs.', '/health', 'Open Health'],
  noScore: ['Health adds IMDb scores, and downloads them for shows that have none yet.', '/health', 'Open Health'],
  duplicates: ['Choose which copy to keep in Duplicates.', '/duplicates', 'Open Duplicates'],
  damaged: ['Health lists these under Needs you, to say which episode each one is.', '/health', 'Open Health'],
};
const FILTERS: [Filter, string][] = [['all', 'All'], ['noNfo', 'Missing NFO'], ['noScore', 'No IMDb score'], ['duplicates', 'Duplicates'], ['damaged', 'Damaged names']];
const art = (path: string) => `/api/library/art?${new URLSearchParams({ path })}`;
const code = (s: number | null, e: number[]) => (s == null ? '—' : `S${String(s).padStart(2, '0')}${e.map((n) => `E${String(n).padStart(2, '0')}`).join('')}`);

// A poster from the library, or the title's initials when there is none (DESIGN.md §8).
function Cover({ src, title, width = '100%', hero = false }: { src: string | null; title: string; width?: number | string; hero?: boolean }) {
  const [failed, setFailed] = useState(false);
  const style = { width, ...(hero ? { viewTransitionName: 'hero' } : {}) };
  if (!src || failed) {
    const initials = title.split(/\s+/).filter((w) => /\w/.test(w)).slice(0, 2).map((w) => w[0]).join('').toUpperCase();
    return <span className="poster" style={style} aria-hidden="true"><span className="poster-initials">{initials || '?'}</span></span>;
  }
  return <img className="poster" style={style} src={src} alt="" loading={hero ? 'eager' : 'lazy'} onError={() => setFailed(true)} />;
}

function Links({ ids, kind }: { ids: Record<string, string>; kind: 'tv' | 'movie' }) {
  const out: [string, string][] = [];
  if (ids.imdb) out.push(['IMDb', `https://www.imdb.com/title/${ids.imdb}/`]);
  if (ids.tmdb) out.push(['TMDB', `https://www.themoviedb.org/${kind}/${ids.tmdb}`]);
  if (ids.tvdb && kind === 'tv') out.push(['TVDB', `https://thetvdb.com/dereferrer/series/${ids.tvdb}`]);
  if (!out.length) return <span className="small muted">No IDs in the NFO</span>;
  return <span className="small">{out.map(([label, href], i) => <span key={label}>{i > 0 && ' · '}<a href={href} target="_blank" rel="noreferrer">{label}</a></span>)}</span>;
}

function problemsText(p: LibProblems, film = false): string[] {
  const out: string[] = [];
  if (p.noNfo) out.push(film ? 'No NFO' : `${p.noNfo} without an NFO`);
  if (p.damaged) out.push(film ? 'Video missing or too small' : `${p.damaged} with a damaged or missing number`);
  if (p.duplicates) out.push(film ? `${p.duplicates + 1} copies` : `${p.duplicates} numbers twice`);
  if (p.loose) out.push(`${p.loose} leftover files`);
  return out;
}

// ---- a show -------------------------------------------------------------------------------
function EpisodeRow({ e }: { e: LibEpisode }) {
  const name = e.file.split('/').pop() ?? e.file;
  const flags = [!e.nfo && 'no NFO', e.damaged && 'damaged number', e.season == null && !e.damaged && 'no number', e.duplicate && 'number twice', e.mismatch && 'NFO says another number']
    .filter(Boolean) as string[];
  return (
    <li style={{ display: 'grid', gridTemplateColumns: '84px minmax(0, 1fr) auto', gap: '2px 12px', alignItems: 'baseline' }}>
      <span className="mono small">{code(e.season, e.episodes)}</span>
      <span style={{ minWidth: 0 }}>
        <span className="ellipsis" style={{ display: 'block' }}>{e.title ?? <span className="muted">—</span>}</span>
        <span className="mono small muted ellipsis" style={{ display: 'block' }} title={e.file}>{middle(name, 70)}</span>
        {flags.length > 0 && <span className="small" style={{ color: 'var(--warn-text)' }}>{flags.join(' · ')}</span>}
        {(e.subLangs?.length ?? 0) > 0 && <span className="small muted" style={{ display: 'block' }}>Subtitles {e.subLangs!.join(' · ')}</span>}
      </span>
      <span style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 2 }}>
        <span className="small num">{score(e.rating) || <span className="muted">no score</span>}</span>
        <span className="status small">{e.watched ? <><Dot kind="dot-success" />Watched</> : e.watched === 0 ? <><Dot />Not watched</> : <span className="muted">—</span>}</span>
      </span>
    </li>
  );
}

function ShowPage({ folder }: { folder: string }) {
  const [show, setShow] = useState<ShowDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [flying] = useState(isFlying);
  useEffect(() => { api.libraryShow(folder).then(setShow).catch((e: Error) => { setError(e.message); heroLanded(); }); }, [folder]);
  useEffect(() => { if (show && flying) heroLanded(); }, [show, flying]);
  const seasons = useMemo(() => {
    const m = new Map<number | null, LibEpisode[]>();
    for (const e of show?.episodes ?? []) m.set(e.season, [...(m.get(e.season) ?? []), e]);
    const byNumber = (a: LibEpisode, b: LibEpisode) => (a.episodes[0] ?? 9999) - (b.episodes[0] ?? 9999) || a.file.localeCompare(b.file);
    return [...m.entries()].sort((a, b) => (a[0] ?? 999) - (b[0] ?? 999)).map(([s, eps]) => [s, [...eps].sort(byNumber)] as const);
  }, [show]);
  const [season, setSeason] = useState<number | null | undefined>(undefined);
  const shown = seasons.find(([s]) => s === season) ?? seasons[0];
  return (
    <div className="page">
      <Link to="/library" className="btn btn-ghost btn-sm" style={{ alignSelf: 'flex-start' }}>← Library</Link>
      {error && <div className="banner banner-error" role="alert">{error}</div>}
      {!show && !error && <Loading rows={4} label="Loading the show" />}
      {show && (
        <>
          <header style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 120px) minmax(0, 1fr)', gap: 20, alignItems: 'start' }}>
            <Cover src={show.poster ? art(`TV/${show.folder}/poster.jpg`) : null} title={show.title} hero={flying} />
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 }}>
              <p className="eyebrow">Show</p>
              <h1 style={{ margin: 0, fontSize: '2rem', overflowWrap: 'anywhere' }}>{show.title}{show.year ? ` (${show.year})` : ''}</h1>
              <span className="mono small muted">TV/{show.folder}/</span>
              <Links ids={show.ids} kind="tv" />
              <span className="small">{show.count} episodes · {show.seasons} seasons · {size(show.size)} · {show.watched} watched{show.rating ? ` · ${score(show.rating)}` : ''}</span>
              {problemsText(show.problems).length > 0 && <span className="small" style={{ color: 'var(--warn-text)' }}>{problemsText(show.problems).join(' · ')}</span>}
              {!show.nfo && <span className="small" style={{ color: 'var(--warn-text)' }}>The show folder has no tvshow.nfo.</span>}
            </div>
          </header>
          {note && <div className="banner banner-note" role="status">{note}</div>}
          <LibraryEditor kind="tv" path={`TV/${show.folder}`} nfo={show.nfo ? `TV/${show.folder}/tvshow.nfo` : null}
            posterTarget={`TV/${show.folder}/poster.jpg`} tmdbId={show.ids.tmdb ? Number(show.ids.tmdb) : null} title={show.title}
            onDone={(text) => { setNote(text); api.libraryShow(folder).then(setShow).catch(() => undefined); }} />
          {seasons.length > 1 && (
            <div className="seg filters" role="group" aria-label="Seasons">
              {seasons.map(([s, eps]) => (
                <button key={String(s)} type="button" aria-pressed={shown?.[0] === s} onClick={() => setSeason(s)}>
                  {s == null ? 'No number' : s === 0 ? 'Specials' : `Season ${s}`}
                  {eps.some((e) => !e.nfo || !e.imdb || e.damaged || e.duplicate) && <Dot kind="dot-warning" />}
                </button>
              ))}
            </div>
          )}
          {shown && (() => {
            const [s, eps] = shown;
            const why = s != null ? show.scoreNotes?.[String(s)] : undefined;
            return (
              <section className="panel" aria-label={s == null ? 'Without a number' : `Season ${s}`}>
                <div className="panel-head">
                  <h2>{s == null ? 'Without a season number' : s === 0 ? 'Specials' : `Season ${s}`}</h2>
                  <span className="small muted">{eps.length} episodes · {eps.filter((e) => e.watched).length} watched</span>
                </div>
                {why && (
                  <p className="hint" style={{ margin: '0 0 8px', color: 'var(--warn-text)' }}>
                    {why}{why.includes('Health') && <> <Link to="/health">Open Health</Link></>}
                  </p>
                )}
                <ul className="rows">{eps.map((e) => <EpisodeRow key={e.file} e={e} />)}</ul>
              </section>
            );
          })()}
          {show.loose.length > 0 && (
            <section className="panel" aria-labelledby="loose-h">
              <div className="panel-head"><h2 id="loose-h">Leftover files</h2><span className="small muted">belong to no video</span></div>
              <ul className="rows">{show.loose.map((f) => <li key={f}><span className="mono small" style={{ wordBreak: 'break-all' }}>{f}</span></li>)}</ul>
            </section>
          )}
        </>
      )}
    </div>
  );
}

// ---- a film -------------------------------------------------------------------------------
function FilmPage({ film }: { film: Film }) {
  const [note, setNote] = useState<string | null>(null);
  const [flying] = useState(isFlying);
  useEffect(() => { if (flying) heroLanded(); }, [flying]);
  const stem = film.file ? `Film/${film.file.replace(/\.[^.]+$/, '')}` : '';
  return (
    <div className="page">
      <Link to="/library?kind=film" className="btn btn-ghost btn-sm" style={{ alignSelf: 'flex-start' }}>← Library</Link>
      <header style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 120px) minmax(0, 1fr)', gap: 20, alignItems: 'start' }}>
        <Cover src={film.poster ? art(`Film/${filmDir(film)}/poster.jpg`) : null} title={film.title} hero={flying} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 }}>
          <p className="eyebrow">Film</p>
          <h1 style={{ margin: 0, fontSize: '2rem', overflowWrap: 'anywhere' }}>{film.title}{film.year ? ` (${film.year})` : ''}</h1>
          <Links ids={film.ids} kind="movie" />
          <span className="small">{score(film.rating) || 'No score in the NFO'} · {film.watched ? 'watched' : film.watched === 0 ? 'not watched' : 'not in the watched backup'}</span>
          {problemsText(film.problems, true).length > 0 && <span className="small" style={{ color: 'var(--warn-text)' }}>{problemsText(film.problems, true).join(' · ')}</span>}
        </div>
      </header>
      {note && <div className="banner banner-note" role="status">{note}</div>}
      {film.file && (
        <LibraryEditor kind="movie" path={`Film/${film.file}`} nfo={film.nfoFile ? `Film/${film.nfoFile}` : null}
          posterTarget={film.folder ? `Film/${film.key}/poster.jpg` : `${stem}-poster.jpg`} tmdbId={film.ids.tmdb ? Number(film.ids.tmdb) : null}
          title={film.title} onDone={setNote} />
      )}
      <section className="panel" aria-labelledby="files-h">
        <div className="panel-head"><h2 id="files-h">Files</h2></div>
        <ul className="rows">
          {film.file && <li><span className="mono small" style={{ wordBreak: 'break-all' }}>Film/{film.file}</span><span className="small num">{size(film.size)}</span></li>}
          {film.others.map((o) => <li key={o}><span className="mono small muted" style={{ wordBreak: 'break-all' }}>Film/{o}</span><span className="small muted">extra or second copy</span></li>)}
          {!film.file && <li><span className="small" style={{ color: 'var(--warn-text)' }}>No video in this folder.</span></li>}
        </ul>
      </section>
    </div>
  );
}

// ---- the grid -----------------------------------------------------------------------------
export function LibraryPage({ status, refresh }: StatusHook) {
  const { search } = useLocation();
  const params = new URLSearchParams(search);
  const kind = params.get('kind') === 'film' ? 'film' : 'tv';
  const filter = (params.get('show') ?? 'all') as Filter;
  const folder = params.get('folder');
  const filmKey = params.get('film');
  const [lib, setLib] = useState<Library | null>(null);
  const [query, setQuery] = useState('');
  const [error, setError] = useState<string | null>(null);
  const running = Boolean(status?.job?.running);

  useEffect(() => { api.library().then(setLib).catch((e: Error) => setError(e.message)); }, [running, status?.job?.finished]);

  const go = (k: string, f: Filter) => navigate(`/library?${new URLSearchParams({ ...(k === 'film' ? { kind: 'film' } : {}), ...(f !== 'all' ? { show: f } : {}) })}`.replace(/\?$/, ''));
  const matches = (title: string, p: LibProblems) => (filter === 'all' || p[filter] > 0) && title.toLowerCase().includes(query.trim().toLowerCase());
  const shows = useMemo(() => (lib?.shows ?? []).filter((s) => matches(s.title, s.problems)), [lib, filter, query]); // eslint-disable-line react-hooks/exhaustive-deps
  const films = useMemo(() => (lib?.films ?? []).filter((f) => matches(f.title, f.problems)), [lib, filter, query]); // eslint-disable-line react-hooks/exhaustive-deps
  const count = (f: Filter) => (kind === 'tv' ? lib?.shows ?? [] : lib?.films ?? []).filter((x: ShowSummary | Film) => f === 'all' || x.problems[f] > 0).length;
  // The button pressed spins until its request is answered; a job then shows in the job bar (DESIGN.md §7.6).
  // Every hook comes before the returns below: the list and a show are one component, and React counts its hooks.
  const [starting, setStarting] = useState<string | null>(null);

  if (folder) return <ShowPage folder={folder} />;
  const film = filmKey ? lib?.films.find((f) => f.key === filmKey) : null;
  if (film) return <FilmPage film={film} />;

  const begin = (key: string, request: () => Promise<unknown>) => {
    setStarting(key);
    setError(null);
    request().then(refresh).catch((e: Error) => setError(e.message)).finally(() => setStarting(null));
  };
  const index = () => begin('index', api.indexLibrary);
  const episodes = (lib?.shows ?? []).reduce((n, s) => n + s.count, 0);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">Library</p>
          <h1>Shows and films</h1>
          <p className="lede">
            {lib?.at ? `${lib.shows.length} shows · ${episodes.toLocaleString('en-GB')} episodes · ${lib.films.length} films · indexed ${when(lib.at)}` : 'Not indexed yet.'}
          </p>
        </div>
        <div className="actions">
          <button className={lib?.at ? 'btn btn-secondary btn-sm' : 'btn btn-primary'} type="button" aria-busy={starting === 'index'} onClick={index}>
            {lib?.at ? 'Index again' : 'Index the library'}
          </button>
        </div>
      </header>
      <JobError job={status?.job} />
      {!lib && !error && <Loading label="Loading the library" />}
      {error && <div className="banner banner-error" role="alert">{error}</div>}
      <div className="inline">
        <div className="seg" role="group" aria-label="Library">
          <button type="button" aria-pressed={kind === 'tv'} onClick={() => go('tv', filter)}>TV</button>
          <button type="button" aria-pressed={kind === 'film'} onClick={() => go('film', filter)}>Film</button>
        </div>
        <input className="field" type="search" aria-label="Find a title" placeholder="Find a title" value={query} onChange={(e) => setQuery(e.target.value)} />
      </div>
      <div className="seg filters" role="group" aria-label="Show">
        {FILTERS.map(([k, label]) => (
          <button key={k} type="button" aria-pressed={filter === k} onClick={() => go(kind, k)}>{label} <span className="num muted">{count(k)}</span></button>
        ))}
      </div>
      {FIX_HINT[filter] && (
        <div className="banner banner-note"><span>{FIX_HINT[filter]![0]}</span><Link to={FIX_HINT[filter]![1]}>{FIX_HINT[filter]![2]}</Link></div>
      )}
      {lib?.at && (kind === 'tv' ? shows : films).length === 0 && <p className="hint">Nothing here with this filter.</p>}
      <div className="posters">
        {kind === 'tv' ? shows.map((s) => (
          <Link key={s.folder} className="poster-tile" to={`/library?${new URLSearchParams({ folder: s.folder })}`} title={s.title}
            onClick={(e) => heroClick(e, `/library?${new URLSearchParams({ folder: s.folder })}`)}>
            <Cover src={s.poster ? art(`TV/${s.folder}/poster.jpg`) : null} title={s.title} />
            <span className="poster-title">{s.title}</span>
            <span className="small muted">{s.year ?? ''}{s.year ? ' · ' : ''}{s.count} ep · {s.watched} watched</span>
          </Link>
        )) : films.map((f) => (
          <Link key={f.key} className="poster-tile" to={`/library?${new URLSearchParams({ kind: 'film', film: f.key })}`} title={f.title}
            onClick={(e) => heroClick(e, `/library?${new URLSearchParams({ kind: 'film', film: f.key })}`)}>
            <Cover src={f.poster ? art(`Film/${filmDir(f)}/poster.jpg`) : null} title={f.title} />
            <span className="poster-title">{f.title}</span>
            <span className="small muted">{f.year ?? '—'}{f.imdb ? ` · IMDb ${f.imdb[0].toFixed(1)}` : ''}{f.watched ? ' · watched' : ''}</span>
          </Link>
        ))}
      </div>
    </div>
  );
}
