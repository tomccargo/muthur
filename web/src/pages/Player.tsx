// The player (docs/PLAYER.md): its own page at /player, outside muthur's sections. TV and Films as a visual grid with
// filters; a show's seasons and episodes; and the watch view, which fits the tab and goes full screen. Read-only:
// the files are played as they are, and nothing about watching is written anywhere.
import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import { api, type Playback, type PlayerFilm, type PlayerInfo, type PlayerItems, type PlayerLinks, type PlayerShow, type PlayerShowTile, type PlayerSub, type PlayerTest } from '../api';
import { Loading } from '../components';
import { hue } from '../labels';
import { Link, navigate, useLocation } from '../nav';
import { art } from './Library';
import './player.css';

type View = 'films' | 'tv' | 'test';
type Sort = 'added' | 'title' | 'year' | 'rating';
type Seen = 'all' | 'unwatched' | 'watched';
const SORTS: [Sort, string][] = [['added', 'Recently added'], ['title', 'Title'], ['year', 'Year'], ['rating', 'Rating']];
type Way = 'native' | 'sound' | 'kodi' | 'unknown';
// H.264 in 10-bit plays in Chrome and Edge but not in Firefox (measured 26 Oct, docs/PLAYER.md §3): decided here, by the browser.
const HI10 = !/firefox/i.test(navigator.userAgent);
const way = (p: Playback): Way => (p.endsWith('-hi10') ? (HI10 ? (p.slice(0, -5) as Way) : 'kodi') : (p as Way));
const MSE = typeof window !== 'undefined' && 'MediaSource' in window;  // repacking in the browser (repack.ts) needs it
const PLAY_NOTE: Record<Way, string | null> = {
  native: null,
  sound: MSE ? null : 'This browser can’t decode this file’s sound (AC3, E-AC3 or DTS): it plays without sound.',
  kodi: 'Plays in Kodi only: no browser plays this kind of file. The ⋯ menu above plays it on the TV, opens it in your own player, or downloads it.',
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
  const kodi = way(f.play) === 'kodi';
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
  if (kodi) return <Link className="pl-tile dim" to={watchUrl(f.id, label)} title={`${label}: plays in Kodi only; open it for the TV, VLC or a download`}>{body}</Link>;
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
      {current != null && (
        <p className="pl-season-tools">
          <a href={`/api/player/zip?${new URLSearchParams({ folder, season: String(current) })}`} download title="Every episode of this season as it is, with its subtitles, in one ZIP (for a laptop)">
            Download {current === 0 ? "the specials" : `season ${current}`} (ZIP)</a>
        </p>
      )}
      <ul className="pl-episodes">
        {show.episodes.filter((e) => e.season === current).map((e) => {
          const name = `${code(e.season, e.episodes)}${e.title ? ` · ${e.title}` : ''}`;
          const inner = (
            <>
              <span className="pl-thumb"><Art path={e.thumb} title={e.title ?? show.title} wide />{way(e.play) !== 'kodi' && <PlayMark />}</span>
              <span className="pl-ep-text"><span className="pl-name">{name}</span>
                <span className="pl-sub">{way(e.play) === 'kodi' ? 'Kodi only' : way(e.play) === 'sound' ? 'Sound in a later step' : ''}{e.watched ? (way(e.play) === 'native' || way(e.play) === 'unknown' ? 'Watched' : ' · Watched') : ''}</span></span>
            </>
          );
          return (
            <li key={e.id}>
              {way(e.play) === 'kodi' ? <Link className="pl-ep dim" to={watchUrl(e.id, `${show.title} ${name}`)} title="Plays in Kodi only; open it for the TV, VLC or a download">{inner}</Link>
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

// ---- open with, download ------------------------------------------------------------------------
// A small menu beside Play (decided 26 Oct): the TV, the phone's own player, the PC's own player, the share path, and
// downloads. A page can't see which players are installed, so each entry simply works or does nothing visible.
const ANDROID = /android/i.test(navigator.userAgent);
const WINDOWS = /windows/i.test(navigator.userAgent);

function OpenMenu({ id, onNote }: { id: string; onNote: (text: string, stay?: boolean) => void }) {
  const [open, setOpen] = useState(false);
  const [links, setLinks] = useState<PlayerLinks | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  useEffect(() => {
    if (open && !links) api.playerLinks(id).then(setLinks).catch((e: Error) => setFailed(e.message));
  }, [open, links, id]);
  const abs = (path: string) => new URL(path, location.origin).href;
  // Android: VLC by name (it takes the .srt along), or any app that plays video (the phone asks which).
  const intent = (pkg: string | null) => {
    if (!links) return '#';
    const u = new URL(links.stream, location.origin);
    const sub = links.subtitles.find((s) => s.lang === 'en' && !s.forced) ?? links.subtitles[0];
    const extras = [`S.title=${encodeURIComponent(links.name)}`, ...(sub && pkg ? [`S.subtitles_location=${encodeURIComponent(abs(sub.url))}`] : [])];
    return `intent://${u.host}${u.pathname}${u.search}#Intent;scheme=${u.protocol.replace(':', '')};type=video/*;${pkg ? `package=${pkg};` : ''}${extras.join(';')};end`;
  };
  const copy = (text: string, what: string) => navigator.clipboard.writeText(text).then(() => onNote(`${what} copied.`), () => onNote(text));
  const tv = () => {
    setOpen(false);
    onNote('Starting on the TV… (if Kodi isn’t running, muthur wakes it first: up to a minute)', true);
    api.playerTv(id).then((r) => onNote(`Playing on ${r.device}.`)).catch((e: Error) => onNote(e.message));
  };
  return (
    <span className="pl-menu">
      <button type="button" className="pl-btn" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)} title="Open with, download">⋯</button>
      {open && (
        <span className="pl-menu-list" role="menu">
          {failed && <span className="pl-menu-note">{failed}</span>}
          {!links && !failed && <span className="pl-menu-note">Loading…</span>}
          {links && (
            <>
              {links.tv && <button type="button" role="menuitem" onClick={tv}>Play on the TV</button>}
              {ANDROID && <a role="menuitem" href={intent('org.videolan.vlc')}>Open in VLC</a>}
              {ANDROID && <a role="menuitem" href={intent(null)}>Open in another app</a>}
              {!ANDROID && (
                <a role="menuitem" href={`/api/player/video/${id}/playlist.m3u${WINDOWS ? '?windows=1' : ''}`} download>Open in your own player (.m3u)</a>
              )}
              {links.share && <button type="button" role="menuitem" onClick={() => copy(WINDOWS ? links.share!.unc : links.share!.smb, 'Path')}>Copy path</button>}
              <button type="button" role="menuitem" onClick={() => copy(abs(links.stream), 'Link (12 hours)')}>Copy link</button>
              <span className="pl-menu-sep" />
              <a role="menuitem" href={`/api/player/video/${id}?download=1`} download>Download video</a>
              {links.subtitles.map((s) => (
                <a key={s.name} role="menuitem" href={`${s.url}&download=1`} download>Download subtitles: {s.label}</a>
              ))}
            </>
          )}
        </span>
      )}
    </span>
  );
}

// ---- watching -------------------------------------------------------------------------------
function Watch({ id, title, mute = false }: { id: string; title: string; mute?: boolean }) {
  const box = useRef<HTMLDivElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  const [info, setInfo] = useState<PlayerInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [full, setFull] = useState(false);
  const [cue, setCue] = useState<'s' | 'm' | 'l'>(() => {
    try { return (localStorage.getItem('muthur.cue') as 's' | 'm' | 'l') || 'm'; } catch { return 'm'; }
  });
  const nextCue = () => {
    const n = cue === 's' ? 'm' : cue === 'm' ? 'l' : 's';
    setCue(n);
    try { localStorage.setItem('muthur.cue', n); } catch { /* the size just isn't remembered */ }
  };
  useEffect(() => { api.playerInfo(id).then(setInfo).catch((e: Error) => setError(e.message)); }, [id]);
  // The subtitle files beside the video; it grows when muthur copies subtitles out of the file (decided 26 Oct).
  const [subList, setSubList] = useState<PlayerSub[]>([]);
  const [subNote, setSubNote] = useState<string | null>(null);
  const [subProgress, setSubProgress] = useState<number | null>(null);
  const [flash, setFlash] = useState<string | null>(null);  // what an Open-with entry just did
  const flashTimer = useRef(0);
  // Said once when the film starts, when there are no full subtitles to show: a film without them otherwise just
  // looks broken (Valerian, Casino Royale, 26 Oct).
  useEffect(() => {
    if (!info || info.extractable.length || info.subtitles.some((s) => !s.forced)) return;
    const forced = info.subtitles.find((s) => s.forced);
    const f = forced ? info.forcedLines[forced.name] : null;
    const at = (s: number | null) => (s == null ? '' : `, the first at ${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`);
    const text = f && f.lines
      ? `Only forced subtitles: ${f.lines} ${f.lines === 1 ? 'line' : 'lines'} for the parts in another language${at(f.first)}.`
      : info.pictureSubs
        ? `Subtitles only as pictures inside the file (${info.pictureSubs} ${info.pictureSubs === 1 ? 'track' : 'tracks'}): a browser can’t show those. Kodi can (⋯, Play on the TV).`
        : 'No subtitles for this video.';
    setFlash(text);
    window.clearTimeout(flashTimer.current);
    flashTimer.current = window.setTimeout(() => setFlash(null), 12000);
  }, [info]);
  useEffect(() => { if (info) setSubList(info.subtitles); }, [info]);
  useEffect(() => {
    if (!info || !info.extractable.length) return;
    if (info.dryRun) {
      setSubNote('This video has subtitles inside; muthur copies them out beside it, but not while dry run is on.');
      return;
    }
    let stop = false;
    setSubNote('Copying the subtitles out of the file…');
    holding.current = true;  // the film waits for its subtitles, then starts by itself
    video.current?.pause();
    setSubProgress(0);
    api.playerExtract(id).then(async () => {
      // ffmpeg reads the whole film: the job says how far (seconds read of the film), shown as a bar.
      for (let i = 0; i < 1200 && !stop; i++) {
        await new Promise((r) => setTimeout(r, 1500));
        const job = await api.job().catch(() => null);
        if (job?.name === 'subtitles-extract' && job.running) {
          if (!stop) {
            setSubProgress(job.total ? job.done / job.total : 0);
            setSubNote(job.queued ? 'Subtitles: waiting for another job to finish…' : 'Copying the subtitles out of the file…');
          }
          continue;
        }
        const fresh = await api.playerInfo(id);
        if (!stop) {
          if (fresh.subtitles.length > info.subtitles.length) setSubList(fresh.subtitles);
          else if (job?.error) setSubNote(`The subtitles couldn’t be copied out: ${job.error}`);
          setSubProgress(null);
          if (!job?.error) setSubNote(null);
          release();
        }
        return;
      }
      if (!stop) release();
    }).catch((e: Error) => {
      if (!stop) { setSubProgress(null); setSubNote(`The subtitles couldn’t be copied out: ${e.message}`); release(); }
    });
    return () => { stop = true; holding.current = false; };
  }, [info, id]);
  // While the subtitles are copied the film waits (autoplay is paused at once); then it starts by itself, with or
  // without them (asked for on 26 Oct).
  const holding = useRef(false);
  const release = () => {
    holding.current = false;
    window.setTimeout(() => void video.current?.play().catch(() => undefined), 400);  // after the new tracks are in
  };
  useEffect(() => {
    const v = video.current;
    if (!v) return;
    const hold = () => { if (holding.current) v.pause(); };
    v.addEventListener('play', hold);
    return () => v.removeEventListener('play', hold);
  }, [info]);
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
  const how = info ? way(info.play) : null;
  // Repack in the browser (docs/PLAYER.md §4) when the sound needs decoding, for every MKV in Firefox (its MKV reader
  // stutters on some), and when the original-language track isn't the file's default; otherwise the file plays directly.
  const defaultAudio = info?.facts ? Math.max(0, info.facts.audio.findIndex((a) => a.default)) : 0;
  const repack = Boolean(info && how !== 'kodi' && MSE
    && (how === 'sound' || (!HI10 && info.facts?.container === '.mkv') || (info.audio != null && info.audio !== defaultAudio)));
  const src = `/api/player/video/${id}`;
  useEffect(() => {
    if (!repack || !info || !video.current) return;
    let engine: { destroy: () => void } | null = null;
    let gone = false;
    import('./repack').then(({ Repack }) => {
      if (gone || !video.current) return;
      const r = new Repack(video.current, src, { audio: info.audio, onError: (m) => setError(`Repacking stopped: ${m}`) });
      engine = r;
      r.start().catch((e: Error) => setError(`Repacking failed: ${e.message}`));
    }).catch((e: Error) => setError(`The repacker didn’t load: ${e.message}`));
    return () => { gone = true; engine?.destroy(); };
  }, [repack, info, src]);
  const note = info && how ? (how === 'kodi' && info.play.endsWith('-hi10') ? 'Firefox doesn’t play this video (H.264 in 10-bit): Chrome, Edge and Kodi do.' : PLAY_NOTE[how]) : null;
  const subs = subList;
  // On by default: full English; else a file whose name gives no language (in this library nearly always English); else
  // English forced subtitles, which only translate the lines in another language (Valerian's aliens) and belong on.
  const firstEnglish = [subs.findIndex((s) => s.lang === 'en' && !s.forced), subs.findIndex((s) => s.lang === 'und' && !s.forced),
    subs.findIndex((s) => (s.lang === 'en' || s.lang === 'und') && s.forced)].find((i) => i >= 0) ?? -1;
  // Which subtitles show. Subtitles the browser recognises inside the file itself come first (English first): they
  // belong to this video (none do in Chrome or Firefox today, measured 26 Oct). Else the file beside it chosen above;
  // a track added after the video loaded isn't switched on by its default attribute, so it is switched on here. Once
  // per set of subtitles: what the reader picks in the CC menu afterwards stays.
  useEffect(() => {
    const v = video.current;
    if (!v) return;
    let done = false;
    const choose = () => {
      if (done) return;
      const ours = new Set([...v.querySelectorAll('track')].map((el) => el.track));
      const inside = [...v.textTracks].filter((t) => !ours.has(t) && (t.kind === 'subtitles' || t.kind === 'captions'));
      const pick = inside.find((t) => t.language.startsWith('en')) ?? inside[0]
        ?? (firstEnglish >= 0 ? v.querySelectorAll('track')[firstEnglish]?.track : undefined);
      if (!pick) return;
      for (const t of v.textTracks) if (t !== pick && t.mode === 'showing') t.mode = 'disabled';
      pick.mode = 'showing';
      done = inside.length > 0 || v.readyState >= 1;
    };
    const t = setTimeout(choose, 300);
    v.addEventListener('loadedmetadata', choose);
    v.textTracks.addEventListener('addtrack', choose);
    return () => { clearTimeout(t); v.removeEventListener('loadedmetadata', choose); v.textTracks.removeEventListener('addtrack', choose); };
  }, [subs, firstEnglish]);
  return (
    <div className={`pl-watch${full ? ' full' : ''}${cue === 'm' ? '' : ` cue-${cue}`}`} ref={box}>
      {error && <p className="pl-watch-msg">{error}</p>}
      {info && how !== 'kodi' && (
        <video ref={video} src={repack ? undefined : src} controls autoPlay playsInline preload="auto" muted={mute}>
          {subs.map((s, i) => (
            <track key={s.name} kind="subtitles" src={`/api/player/video/${id}/subtitles/${encodeURIComponent(s.name)}`}
              srcLang={s.lang === 'und' ? undefined : s.lang} label={s.label} default={i === firstEnglish} />
          ))}
        </video>
      )}
      <div className="pl-watch-top">
        <button type="button" className="pl-btn" onClick={back} aria-label="Back">←</button>
        <span className="pl-watch-title" title={info?.path}>{title}</span>
        {info && how !== 'kodi' && <span className="pl-watch-how" title="How this video plays">{repack ? 'repacked in the browser' : 'direct'}</span>}
        <OpenMenu id={id} onNote={(t, stay) => { window.clearTimeout(flashTimer.current); setFlash(t); if (!stay) flashTimer.current = window.setTimeout(() => setFlash(null), 5000); }} />
        {subs.length > 0 && (
          <button type="button" className="pl-btn" onClick={nextCue} title={`Subtitle size: ${cue === 's' ? 'small' : cue === 'm' ? 'medium' : 'large'}`}
            aria-label="Subtitle size">{cue === 's' ? 'a' : cue === 'm' ? 'Aa' : 'AA'}</button>
        )}
        <button type="button" className="pl-btn" onClick={toggleFull} aria-label={full ? 'Leave full screen' : 'Full screen'}>{full ? '⤡' : '⤢'}</button>
      </div>
      {note && <p className={`pl-watch-msg${how === 'kodi' ? '' : ' corner'}`}>{note}</p>}
      {flash && <p className="pl-watch-msg corner" role="status">{flash}</p>}
      {subNote && !note && !flash && (
        <div className="pl-watch-msg corner" role="status">
          <span>{subNote}{subProgress != null && subProgress > 0 ? ` ${Math.round(subProgress * 100)}%` : ""}</span>
          {subProgress != null && <span className={`pl-progress${subProgress > 0 ? "" : " busy"}`}><span style={{ width: `${Math.max(4, subProgress * 100)}%` }} /></span>}
        </div>
      )}
      {!info && !error && <p className="pl-watch-msg">Loading…</p>}
    </div>
  );
}

export default function PlayerApp() {
  const { path, search } = useLocation();
  const q = new URLSearchParams(search);
  if (path === '/player/watch' && q.get('id')) return <Watch id={q.get('id')!} title={q.get('t') ?? 'Video'} mute={q.get('mute') === '1'} />;
  const view = (q.get('view') ?? 'films') as View;
  return <Browse view={['films', 'tv', 'test'].includes(view) ? view : 'films'} show={q.get('show')} />;
}
