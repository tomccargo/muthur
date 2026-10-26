// The player (docs/PLAYER.md): its own page at /player, outside muthur's sections. TV and Films as a visual grid with
// filters; a show's seasons and episodes; and the watch view, which fits the tab and goes full screen. Read-only:
// the files are played as they are, and nothing about watching is written anywhere.
import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import { api, type Playback, type PlayerFilm, type PlayerInfo, type PlayerItems, type PlayerShow, type PlayerShowTile, type PlayerTest } from '../api';
import { Loading } from '../components';
import { hue } from '../labels';
import { Link, navigate, useLocation } from '../nav';
import { art } from './Library';
import './player.css';

type View = 'films' | 'tv' | 'test';
type Sort = 'added' | 'title' | 'year' | 'rating';
type Seen = 'all' | 'unwatched' | 'watched';
const SORTS: [Sort, string][] = [['added', 'Recently added'], ['title', 'Title'], ['year', 'Year'], ['rating', 'Rating']];
const PLAY_NOTE: Record<Playback, string | null> = {
  native: null,
  sound: 'Sound in a later step: the browser shows the picture, but this file’s sound (AC3, E-AC3 or DTS) needs the page to decode it.',
  kodi: 'Plays in Kodi only: no browser plays this kind of file.',
  unknown: null,
};
const code = (s: number | null, e: number[]) => (s == null ? '' : `S${String(s).padStart(2, '0')}${e.map((n) => `E${String(n).padStart(2, '0')}`).join('')}`);
const watchUrl = (id: string, title: string) => `/player/watch?${new URLSearchParams({ id, t: title })}`;

// A poster or thumbnail from the library, or the title's initials on a coloured card when there is none.
function Art({ path, title, wide = false }: { path: string | null; title: string; wide?: boolean }) {
  const [failed, setFailed] = useState(false);
  if (!path || failed) {
    const initials = title.split(/\s+/).filter((w) => /\w/.test(w)).slice(0, 2).map((w) => w[0]).join('').toUpperCase();
    return <span className={`pl-art pl-art-empty${wide ? ' wide' : ''}`} style={{ '--hue': hue(title) } as CSSProperties} aria-hidden="true">{initials || '?'}</span>;
  }
  return <img className={`pl-art${wide ? ' wide' : ''}`} src={art(path)} alt="" loading="lazy" onError={() => setFailed(true)} />;
}

function PlayMark() {
  return <span className="pl-play" aria-hidden="true"><svg viewBox="0 0 24 24" width="28" height="28"><path d="M8 5v14l11-7z" fill="currentColor" /></svg></span>;
}

// ---- browsing -------------------------------------------------------------------------------
function useFilters(genres: string[]) {
  const [text, setText] = useState('');
  const [genre, setGenre] = useState('');
  const [seen, setSeen] = useState<Seen>('all');
  const [decade, setDecade] = useState('');
  const [minRating, setMinRating] = useState(0);
  const [sort, setSort] = useState<Sort>('added');
  const keep = <T extends { title: string; year: number | null; genres: string[]; rating: number | null }>(x: T, watched: boolean, partly = false) =>
    (!text || x.title.toLowerCase().includes(text.toLowerCase()))
    && (!genre || x.genres.includes(genre))
    && (seen === 'all' || (seen === 'watched' ? watched : !watched || partly))
    && (!decade || (x.year != null && String(Math.floor(x.year / 10) * 10) === decade))
    && (!minRating || (x.rating ?? 0) >= minRating);
  const order = <T extends { title: string; year: number | null; rating: number | null; added: number }>(list: T[]) => [...list].sort((a, b) =>
    sort === 'title' ? a.title.localeCompare(b.title) : sort === 'year' ? (b.year ?? 0) - (a.year ?? 0)
      : sort === 'rating' ? (b.rating ?? 0) - (a.rating ?? 0) : b.added - a.added);
  const bar = (
    <div className="pl-filters" role="search">
      <input type="search" placeholder="Search titles" value={text} onChange={(e) => setText(e.target.value)} aria-label="Search titles" />
      <select value={genre} onChange={(e) => setGenre(e.target.value)} aria-label="Genre">
        <option value="">All genres</option>
        {genres.map((g) => <option key={g} value={g}>{g}</option>)}
      </select>
      <select value={decade} onChange={(e) => setDecade(e.target.value)} aria-label="Decade">
        <option value="">Any year</option>
        {['2020', '2010', '2000', '1990', '1980', '1970', '1960', '1950'].map((d) => <option key={d} value={d}>{d}s</option>)}
      </select>
      <select value={minRating} onChange={(e) => setMinRating(Number(e.target.value))} aria-label="Rating">
        <option value={0}>Any rating</option>
        {[6, 7, 8].map((r) => <option key={r} value={r}>{r}+</option>)}
      </select>
      <span className="pl-seg" role="group" aria-label="Watched">
        {(['all', 'unwatched', 'watched'] as Seen[]).map((s) => (
          <button key={s} type="button" aria-pressed={seen === s} onClick={() => setSeen(s)}>{s === 'all' ? 'All' : s === 'watched' ? 'Watched' : 'Unwatched'}</button>
        ))}
      </span>
      <select value={sort} onChange={(e) => setSort(e.target.value as Sort)} aria-label="Sort">
        {SORTS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
      </select>
    </div>
  );
  return { keep, order, bar };
}

function FilmTile({ f }: { f: PlayerFilm }) {
  const kodi = f.play === 'kodi';
  const label = `${f.title}${f.year ? ` (${f.year})` : ''}`;
  const body = (
    <>
      <span className="pl-cover"><Art path={f.poster} title={f.title} />{!kodi && <PlayMark />}
        {kodi && <span className="pl-badge">Kodi only</span>}
        {f.watched && <span className="pl-tick" title="Watched" aria-label="Watched">✓</span>}</span>
      <span className="pl-name">{f.title}</span>
      <span className="pl-sub">{[f.year, f.rating ? `★ ${f.rating.toFixed(1)}` : null].filter(Boolean).join(' · ')}</span>
    </>
  );
  if (kodi) return <div className="pl-tile dim" title={`${label}: plays in Kodi only`}>{body}</div>;
  return <Link className="pl-tile" to={watchUrl(f.id, label)} title={`Play ${label}`}>{body}</Link>;
}

function ShowTile({ s }: { s: PlayerShowTile }) {
  return (
    <Link className="pl-tile" to={`/player?${new URLSearchParams({ show: s.folder })}`} title={s.title}>
      <span className="pl-cover"><Art path={s.poster} title={s.title} />
        {s.watched === s.episodes && <span className="pl-tick" title="All watched" aria-label="All watched">✓</span>}</span>
      <span className="pl-name">{s.title}</span>
      <span className="pl-sub">{[s.year, `${s.episodes} ep.`, s.rating ? `★ ${s.rating.toFixed(1)}` : null].filter(Boolean).join(' · ')}</span>
    </Link>
  );
}

function Grid({ items, view }: { items: PlayerItems; view: 'films' | 'tv' }) {
  const list = view === 'films' ? items.films : items.shows;
  const genres = useMemo(() => [...new Set(list.flatMap((x) => x.genres))].sort(), [list]);
  const { keep, order, bar } = useFilters(genres);
  const films = order(items.films.filter((f) => keep(f, f.watched)));
  const shows = order(items.shows.filter((s) => keep(s, s.watched === s.episodes, s.watched < s.episodes)));
  const shown = view === 'films' ? films.length : shows.length;
  return (
    <>
      {bar}
      <p className="pl-count">{shown.toLocaleString('en-GB')} {view === 'films' ? (shown === 1 ? 'film' : 'films') : (shown === 1 ? 'show' : 'shows')}</p>
      <div className="pl-grid">
        {view === 'films' ? films.map((f) => <FilmTile key={f.id} f={f} />) : shows.map((s) => <ShowTile key={s.folder} s={s} />)}
      </div>
    </>
  );
}

function TestSet() {
  const [items, setItems] = useState<PlayerTest[] | null>(null);
  useEffect(() => { api.playerTestSet().then((r) => setItems(r.items)).catch(() => setItems([])); }, []);
  if (!items) return <Loading label="Loading the test set" />;
  if (!items.length) return <p className="pl-empty">No test set yet.</p>;
  return (
    <>
      <p className="pl-count">One real file per kind (docs/PLAYER.md). Play each in Firefox, Chrome and Edge.</p>
      <div className="pl-grid">
        {items.map((t) => (
          <Link key={t.id} className="pl-tile" to={watchUrl(t.id, t.kind)} title={t.path}>
            <span className="pl-cover"><Art path={t.art} title={t.kind} /><PlayMark /></span>
            <span className="pl-name">{t.kind}</span>
            <span className="pl-sub">{t.name}</span>
          </Link>
        ))}
      </div>
    </>
  );
}

function ShowView({ folder }: { folder: string }) {
  const [show, setShow] = useState<PlayerShow | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [season, setSeason] = useState<number | null | undefined>(undefined);
  useEffect(() => { api.playerShow(folder).then(setShow).catch((e: Error) => setError(e.message)); }, [folder]);
  if (error) return <p className="pl-empty">{error}</p>;
  if (!show) return <Loading label="Loading the show" />;
  const seasons = [...new Set(show.episodes.map((e) => e.season))].sort((a, b) => (a ?? 999) - (b ?? 999));
  const current = season === undefined ? (seasons.find((s) => show.episodes.some((e) => e.season === s && !e.watched)) ?? seasons[0]) : season;
  return (
    <div className="pl-show">
      <header className="pl-hero" style={show.fanart ? { backgroundImage: `url("${art(show.fanart)}")` } : undefined}>
        <div className="pl-hero-in">
          <span className="pl-hero-poster"><Art path={show.poster} title={show.title} /></span>
          <div>
            <h1>{show.title}</h1>
            <p className="pl-sub">{[show.year, show.genres.join(', '), show.rating ? `★ ${show.rating.toFixed(1)}` : null].filter(Boolean).join(' · ')}</p>
            {show.plot && <p className="pl-plot">{show.plot}</p>}
          </div>
        </div>
      </header>
      <div className="pl-seasons" role="tablist" aria-label="Seasons">
        {seasons.map((s) => (
          <button key={String(s)} type="button" role="tab" aria-selected={s === current} onClick={() => setSeason(s)}>
            {s == null ? 'Other' : s === 0 ? 'Specials' : `Season ${s}`}
          </button>
        ))}
      </div>
      <ul className="pl-episodes">
        {show.episodes.filter((e) => e.season === current).map((e) => {
          const name = `${code(e.season, e.episodes)}${e.title ? ` · ${e.title}` : ''}`;
          const inner = (
            <>
              <span className="pl-thumb"><Art path={e.thumb} title={e.title ?? show.title} wide />{e.play !== 'kodi' && <PlayMark />}</span>
              <span className="pl-ep-text"><span className="pl-name">{name}</span>
                <span className="pl-sub">{e.play === 'kodi' ? 'Kodi only' : e.play === 'sound' ? 'Sound in a later step' : ''}{e.watched ? (e.play === 'native' || e.play === 'unknown' ? 'Watched' : ' · Watched') : ''}</span></span>
            </>
          );
          return (
            <li key={e.id}>
              {e.play === 'kodi' ? <div className="pl-ep dim">{inner}</div>
                : <Link className="pl-ep" to={watchUrl(e.id, `${show.title} ${name}`)}>{inner}</Link>}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function Browse({ view, show }: { view: View; show: string | null }) {
  const [items, setItems] = useState<PlayerItems | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.playerItems().then(setItems).catch((e: Error) => setError(e.message)); }, []);
  const nav: [View, string][] = [['films', 'Films'], ['tv', 'TV'], ['test', 'Test set']];
  return (
    <div className="pl">
      <aside className="pl-side" aria-label="Player">
        <Link to="/" className="pl-brand" title="Back to muthur">muthur <span>· watch</span></Link>
        <nav className="pl-nav">
          {nav.map(([v, label]) => (
            <Link key={v} to={v === 'films' ? '/player' : `/player?view=${v}`} aria-current={!show && view === v ? 'page' : undefined}>{label}</Link>
          ))}
        </nav>
      </aside>
      <main className="pl-main" id="main">
        {error && <p className="pl-empty">{error}</p>}
        {show ? <ShowView folder={show} /> : view === 'test' ? <TestSet /> : items ? <Grid items={items} view={view} /> : !error && <Loading label="Loading the library" />}
      </main>
    </div>
  );
}

// ---- watching -------------------------------------------------------------------------------
function Watch({ id, title }: { id: string; title: string }) {
  const box = useRef<HTMLDivElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  const [info, setInfo] = useState<PlayerInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [full, setFull] = useState(false);
  useEffect(() => { api.playerInfo(id).then(setInfo).catch((e: Error) => setError(e.message)); }, [id]);
  useEffect(() => {
    const onFull = () => setFull(document.fullscreenElement === box.current);
    document.addEventListener('fullscreenchange', onFull);
    return () => document.removeEventListener('fullscreenchange', onFull);
  }, []);
  const back = () => (history.length > 1 ? history.back() : navigate('/player'));
  const toggleFull = () => (document.fullscreenElement ? document.exitFullscreen() : box.current?.requestFullscreen());
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const v = video.current;
      if (!v || e.target instanceof HTMLInputElement) return;
      if (e.key === 'f' || e.key === 'F') toggleFull();
      else if (e.key === 'm' || e.key === 'M') v.muted = !v.muted;
      else if (e.key === 'ArrowRight' && e.target === document.body) v.currentTime += 10;
      else if (e.key === 'ArrowLeft' && e.target === document.body) v.currentTime -= 10;
      else if (e.key === ' ' && e.target === document.body) { e.preventDefault(); if (v.paused) v.play(); else v.pause(); }
      else if (e.key === 'Escape' && !document.fullscreenElement) back();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });
  useEffect(() => { document.title = `${title} · muthur`; }, [title]);
  const note = info ? PLAY_NOTE[info.play] : null;
  const firstEnglish = info?.subtitles.findIndex((s) => s.lang === 'en' && !s.forced) ?? -1;
  return (
    <div className={`pl-watch${full ? ' full' : ''}`} ref={box}>
      {error && <p className="pl-watch-msg">{error}</p>}
      {info && info.play !== 'kodi' && (
        <video ref={video} src={`/api/player/video/${id}`} controls autoPlay playsInline preload="auto">
          {info.subtitles.map((s, i) => (
            <track key={s.name} kind="subtitles" src={`/api/player/video/${id}/subtitles/${encodeURIComponent(s.name)}`}
              srcLang={s.lang === 'und' ? undefined : s.lang} label={s.label} default={i === firstEnglish} />
          ))}
        </video>
      )}
      <div className="pl-watch-top">
        <button type="button" className="pl-btn" onClick={back} aria-label="Back">←</button>
        <span className="pl-watch-title" title={info?.path}>{title}</span>
        <button type="button" className="pl-btn" onClick={toggleFull} aria-label={full ? 'Leave full screen' : 'Full screen'}>{full ? '⤡' : '⤢'}</button>
      </div>
      {note && <p className={`pl-watch-msg${info?.play === 'kodi' ? '' : ' corner'}`}>{note}</p>}
      {!info && !error && <p className="pl-watch-msg">Loading…</p>}
    </div>
  );
}

export default function PlayerApp() {
  const { path, search } = useLocation();
  const q = new URLSearchParams(search);
  if (path === '/player/watch' && q.get('id')) return <Watch id={q.get('id')!} title={q.get('t') ?? 'Video'} />;
  const view = (q.get('view') ?? 'films') as View;
  return <Browse view={['films', 'tv', 'test'].includes(view) ? view : 'films'} show={q.get('show')} />;
}
