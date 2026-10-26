import { useEffect, useRef, useState } from 'react';
import { QuarantinePanel } from './Quarantine';
import { TitleCard } from './Review';
import type { Card, DupGroup, Kind, Season } from '../api';
import { api, type FixKind, type FixResult, type Fixes, type Question } from '../api';
import type { StatusHook } from '../App';
import { Dot, JobError, Loading } from '../components';
import { count, libraryPath, middle, when } from '../labels';
import { Link } from '../nav';

// What each fix does to the reader's files (DESIGN.md §1.7: name what happens, not the record).
const FIX: Record<FixKind, { title: string; what: string }> = {
  'imdb-data': { title: 'Download IMDb scores for shows that have none yet', what: 'Then muthur’s own NFOs get their scores; other NFOs follow as “Add IMDb scores”.' },
  'imdb-scores': { title: 'Add IMDb scores to NFOs', what: 'Adds IMDb’s score as the one Kodi shows. Other ratings in the NFO stay; a copy of each old NFO is kept. Kodi re-reads each item.' },
  'episode-nfos': { title: 'Write NFOs for episodes that have none', what: 'Writes an NFO (and a thumbnail where missing) from TMDB, with IMDb’s score. Only for seasons TMDB numbers the way your library does.' },
  'show-nfos': { title: 'Write tvshow.nfo for show folders that have none', what: 'Writes the show’s NFO, poster, fanart and logo from TMDB where they’re missing.' },
  'film-nfos': { title: 'Write NFOs for films that have none', what: 'Writes the NFO, poster, fanart and logo from TMDB where missing, for films muthur recognises with certainty by name, year and length.' },
  renames: { title: 'Rename episodes to the library’s naming', what: 'Show - S01E02 - TMDB’s title, with the NFO, thumbnail and subtitles. Only while Kodi is on: it keeps each episode’s watched status.' },
  'film-renames': { title: 'Rename films to the library’s naming', what: 'Title (Year)/Title (Year), from the NFO, with the artwork and subtitles; download-site notes go to quarantine. Only while Kodi is on.' },
  posters: { title: 'Replace missing and poor posters', what: 'TMDB’s poster where there is none, or one under 500 pixels wide or not poster-shaped. The old one is kept; Kodi re-reads each item.' },
  subtitles: { title: 'Put subtitles where Kodi finds them', what: 'English goes beside the video under its name (Dutch only when there is no English); other languages, extra copies and Dutch next to English go to quarantine.' },
  leftovers: { title: 'Move leftover files to quarantine', what: 'Tracker notes, Thumbs.db, and NFOs, thumbnails or subtitles of videos that are gone.' },
  'empty-films': { title: 'Move film folders without a video to quarantine', what: 'Folders that only hold an NFO or artwork.' },
  'kodi-entries': { title: 'Remove old entries from Kodi', what: 'Films and episodes Kodi lists twice: once where the video was before a rename, or twice for the same file. The entry that stays gets the watched status first. Only while Kodi is on; no files change.' },
  'subtitle-timing': { title: 'Stretch subtitles that are out of sync', what: 'Subtitle files from another release: too fast, too slow or shifted, measured against the subtitles inside the video. A stretched copy takes their place; the original goes to quarantine.' },
  'subtitle-misfit': { title: 'Move subtitles that don’t fit to quarantine', what: 'Subtitle files that match the video nowhere, even stretched (another cut of the film).' },
  extras: { title: 'Move extras to the show’s Extras folder', what: 'Interviews, featurettes, openings and the like that sit between the episodes. Kodi doesn’t list them as episodes; in Extras its Extras add-on finds them. Nothing else changes.' },
};
const ORDER: FixKind[] = ['imdb-data', 'imdb-scores', 'episode-nfos', 'show-nfos', 'film-nfos', 'posters', 'subtitles', 'subtitle-timing', 'subtitle-misfit', 'renames', 'film-renames', 'kodi-entries', 'extras', 'leftovers', 'empty-films'];
// The fixes in three groups, with "Questions for you" between the second and third (DESIGN.md §1.11): a few titled groups read better than eleven tiles.
export const GROUPS: { id: string; title: string; kinds: FixKind[] }[] = [
  { id: 'scores', title: 'IMDb scores', kinds: ['imdb-data', 'imdb-scores'] },  // shown first, then Missing in Kodi, the questions, Tidy up
  { id: 'kodi', title: 'Missing in Kodi', kinds: ['episode-nfos', 'show-nfos', 'film-nfos', 'posters', 'subtitles'] },
  { id: 'tidy', title: 'Tidy up', kinds: ['renames', 'film-renames', 'subtitle-timing', 'subtitle-misfit', 'kodi-entries', 'extras', 'leftovers', 'empty-films'] },
];

// The answers to a question about an episode's number (or a season's): which episode it is, that its number is
// right, or the show's page; leaving it as is stays possible.
function EpisodeAnswers({ q, kind, onDone, leave }: { q: Question; kind: string; onDone: (text: string) => void; leave: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [picker, setPicker] = useState<Season | null>(null);
  const [season, setSeason] = useState<number>(Number((q.path.match(/S(\d{1,3})E\d/i) ?? [])[1] ?? q.season ?? 1));
  const [episode, setEpisode] = useState<number | null>(null);
  const folder = q.path.split('/')[1] ?? '';
  const run = (key: string, request: () => Promise<unknown>, text: string) => {
    setBusy(key);
    setError(null);
    request().then(() => onDone(text)).catch((e: Error) => setError(e.message)).finally(() => setBusy(null));
  };
  const load = (s: number) => {
    if (!q.tmdb) return;
    setSeason(s);
    setEpisode(null);
    api.season(q.tmdb, s).then(setPicker).catch((e: Error) => setError(e.message));
  };
  const picked = picker?.episodes.find((x) => x.episode === episode);
  // TMDB's other orders for the show (DVD, production…), with how many of its files each fits.
  const [orders, setOrders] = useState<Awaited<ReturnType<typeof api.libraryOrders>> | null>(null);
  const loadOrders = () => {
    setBusy('orders');
    api.libraryOrders(folder).then(setOrders).catch((e: Error) => setError(e.message)).finally(() => setBusy(null));
  };
  return (
    <span style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <span className="actions">
        {kind === 'seasons' && !orders && (
          <button type="button" className="btn btn-secondary btn-sm" aria-busy={busy === 'orders'} onClick={loadOrders}
            title="TMDB keeps other orders for many shows (DVD, production): one may match your files">Use another order</button>
        )}
        {kind === 'numbers' && q.tmdb && !picker && <button type="button" className="btn btn-secondary btn-sm" onClick={() => load(season)}>Which episode is it?</button>}
        {kind === 'numbers' && !q.noNumber && (
          <button type="button" className="btn btn-secondary btn-sm" aria-busy={busy === 'trust'}
            title="Its NFO and score are written by this number at the next fix; nothing is renamed by this"
            onClick={() => run('trust', () => api.trustNumber(q.path), `${q.show ?? folder}: the number of ${q.path.split('/').pop()} is taken as right.`)}>The number is right</button>
        )}
        <Link to={`/library?${new URLSearchParams({ folder })}`} className="btn btn-ghost btn-sm">Open the show</Link>
        <button type="button" className="btn-link small" onClick={leave}>Leave as is</button>
      </span>
      {picker && (
        <span className="actions">
          <select className="field" aria-label="Season" value={season} onChange={(e) => load(Number(e.target.value))} style={{ width: 'auto' }}>
            {picker.seasons.map((s) => <option key={s.season} value={s.season}>{s.season === 0 ? 'Specials' : `Season ${s.season}`}</option>)}
          </select>
          <select className="field" aria-label="Episode" value={episode ?? ''} onChange={(e) => setEpisode(Number(e.target.value) || null)} style={{ width: 'auto', maxWidth: '100%' }}>
            <option value="">Which episode?</option>
            {picker.episodes.map((x) => <option key={x.episode} value={x.episode}>{`E${String(x.episode).padStart(2, '0')}`} · {x.title ?? '—'}</option>)}
          </select>
          {picked && (
            <button type="button" className="btn btn-secondary btn-sm" aria-busy={busy === 'rename'}
              onClick={() => run('rename', () => api.episodeRename(q.path, { season, episode: picked.episode }),
                `Renaming to S${String(season).padStart(2, '0')}E${String(picked.episode).padStart(2, '0')} “${picked.title}”: the bar at the top shows it.`)}>
              It’s S{String(season).padStart(2, '0')}E{String(picked.episode).padStart(2, '0')} “{picked.title}”
            </button>
          )}
        </span>
      )}
      {picker && <span className="small muted">The file gets that number and title, and its NFO describes that episode. Kodi keeps the watched status (Kodi has to be on).</span>}
      {orders && (orders.orders.length === 0
        ? <span className="small muted">TMDB has no other order for {q.show ?? folder}.</span>
        : (
          <ul className="rows">
            {orders.orders.map((o) => (
              <li key={o.id}>
                <span style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
                  <strong>{o.name}</strong>
                  <span className="small muted">{o.kind} order · {count(o.seasons, 'season')} · {count(o.episodes, 'episode')} · fits {o.fits} of your {count(orders.files, 'file')}</span>
                </span>
                {orders.current === o.id
                  ? <button type="button" className="btn btn-ghost btn-sm" aria-busy={busy === 'own'}
                      onClick={() => run('own', () => api.setOrder(folder, null), `${q.show ?? folder} is read by TMDB’s own order again.`)}>Back to TMDB’s order</button>
                  : <button type="button" className="btn btn-secondary btn-sm" aria-busy={busy === o.id}
                      onClick={() => run(o.id, () => api.setOrder(folder, o.id), `${q.show ?? folder} is read by “${o.name}” now; its fixes and questions are updated.`)}>Use this order</button>}
              </li>
            ))}
          </ul>
        ))}
      {error && <span className="banner banner-error" role="alert">{error}</span>}
    </span>
  );
}
// 'TV/The Office (US)' for a question inside a show's folder; null for anything else.
const showOf = (q: Question | undefined) => (q && q.path.startsWith('TV/') && q.path.split('/').length > 1 ? q.path.split('/').slice(0, 2).join('/') : null);

const QUESTIONS: Record<string, string> = {
  seasons: 'Seasons numbered differently from TMDB',
  numbers: 'Episodes whose number can’t be trusted',
  shows: 'Shows muthur can’t find on TMDB',
  films: 'Films without an NFO',
};

// "Which is it?" for a show or film muthur can't place: a TMDB search right in the list.
function Chooser({ kind, path, busy, onDone }: { kind: Kind; path: string; busy: boolean; onDone: (text: string) => void }) {
  const name = path.split('/').filter(Boolean)[kind === 'tv' ? 1 : path.split('/').length - 1] ?? path;
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState(name.replace(/\.[a-z0-9]{2,4}$/i, '').replace(/[._]+/g, ' '));
  const [cards, setCards] = useState<Card[] | null>(null);
  const [picked, setPicked] = useState<Card | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (!open) return <button className="btn-link small" type="button" style={{ alignSelf: 'flex-start' }} onClick={() => setOpen(true)}>Which is it?</button>;
  const search = () => { setError(null); api.search(kind, query).then((r) => { setCards(r.results); setPicked(null); }).catch((e: Error) => setError(e.message)); };
  const choose = () => {
    if (!picked) return;
    api.chooseForLibrary(kind, path, picked.tmdbId)
      .then((r) => onDone(`${picked.title}${picked.year ? ` (${picked.year})` : ''}: ${count(Object.values(r.fixes).reduce((a, b) => a + (b ?? 0), 0), 'fix', 'fixes')} added${r.questions ? `, ${count(r.questions, 'question')} left` : ''}.`))
      .catch((e: Error) => setError(e.message));
  };
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, paddingTop: 6 }}>
      <form className="inline" onSubmit={(e) => { e.preventDefault(); search(); }}>
        <input className="field" aria-label="Title" value={query} onChange={(e) => setQuery(e.target.value)} />
        <button className="btn btn-secondary btn-sm" type="submit" disabled={!query.trim()}>Search TMDB</button>
      </form>
      {cards && (cards.length ? (
        <div className="cards">{cards.slice(0, 6).map((c) => <TitleCard key={c.tmdbId} card={c} pressed={picked?.tmdbId === c.tmdbId} onPick={() => setPicked(c)} />)}</div>
      ) : <p className="hint">Nothing found; try another spelling.</p>)}
      {error && <div className="banner banner-error" role="alert">{error}</div>}
      {picked && <button className="btn btn-secondary btn-sm" type="button" disabled={busy} aria-busy={busy} style={{ alignSelf: 'flex-start' }} onClick={choose}>It’s {picked.title}{picked.year ? ` (${picked.year})` : ''}</button>}
    </div>
  );
}

// Videos on disk more than once, by name: its own panel, because only the reader can choose the copy to keep
// (DESIGN.md §1.11). The choosing happens in Duplicates.
function DuplicatesPanel({ groups }: { groups: DupGroup[] }) {
  if (!groups.length) return null;
  const films = groups.filter((g) => g.kind === 'film');
  const shows = new Map<string, string[]>();
  for (const g of groups.filter((x) => x.kind === 'episode')) {
    shows.set(g.title, [...(shows.get(g.title) ?? []), g.label.slice(g.title.length).trim()]);
  }
  const episodes = groups.length - films.length;
  return (
    <section id="duplicates" className="panel" aria-labelledby="dups-h" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div className="panel-head" style={{ marginBottom: 0 }}><h2 id="dups-h">Duplicates</h2>
        <span className="num">{groups.length.toLocaleString('en-GB')}</span></div>
      <span className="small muted">On disk more than once. You choose the copy that stays; the others go to quarantine, and Kodi keeps the watched status.</span>
      <ul className="rows">
        {films.length > 0 && (
          <li style={{ flexDirection: 'column', alignItems: 'stretch', gap: 2 }}>
            <strong>{count(films.length, 'film')}</strong>
            <span className="small">{films.map((g) => g.label).join(' · ')}</span>
          </li>
        )}
        {episodes > 0 && (
          <li style={{ flexDirection: 'column', alignItems: 'stretch', gap: 2 }}>
            <strong>{count(episodes, 'episode')}</strong>
            <span className="small">{[...shows].map(([show, eps]) => `${show} ${eps.join(', ')}`).join(' · ')}</span>
          </li>
        )}
      </ul>
      <span className="actions"><Link to="/duplicates" className="btn btn-secondary">Choose which copy to keep</Link></span>
    </section>
  );
}

export function HealthPage({ status, refresh }: StatusHook) {
  const [data, setData] = useState<Fixes | null>(null);
  const [chosen, setChosen] = useState<Set<FixKind>>(new Set());
  const [asking, setAsking] = useState(false);
  const [last, setLast] = useState<FixResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [showLeft, setShowLeft] = useState(false);
  const running = Boolean(status?.job?.running);
  const leave = (body: { items?: Question[]; under?: string; back?: boolean }) => {
    api.leaveQuestions(body).then(() => api.fixes(showLeft)).then(setData).catch((e: Error) => setError(e.message));
  };

  const [dupGroups, setDupGroups] = useState<DupGroup[]>([]);
  useEffect(() => {
    api.fixes(showLeft).then((d) => { setData(d); setChosen(new Set()); }).catch((e: Error) => setError(e.message));
    api.fixesLast().then((r) => setLast('done' in r ? (r as FixResult) : null)).catch(() => undefined);
    api.duplicates().then((d) => setDupGroups(d.groups)).catch(() => undefined);
  }, [running, status?.job?.finished, showLeft]);
  // A Dashboard tile opens its own panel here ('/health#tidy'), once the panels are drawn.
  const jumped = useRef(false);
  useEffect(() => {
    const id = location.hash.slice(1);
    if (!data || jumped.current || !id) return;
    jumped.current = true;
    document.getElementById(id)?.scrollIntoView({ block: 'start' });
  }, [data]);

  const available = ORDER.filter((k) => (data?.fixes[k]?.count ?? 0) > 0);
  const total = [...chosen].reduce((n, k) => n + (data?.fixes[k]?.count ?? 0), 0);
  const toggle = (k: FixKind, on: boolean) => setChosen((s) => { const n = new Set(s); if (on) n.add(k); else n.delete(k); return n; });
  // The button pressed spins until its request is answered; a job then shows in the job bar (DESIGN.md §7.6).
  const [starting, setStarting] = useState<string | null>(null);
  const begin = (key: string, request: () => Promise<unknown>) => {
    setStarting(key);
    setError(null);
    request().then(refresh).catch((e: Error) => setError(e.message)).finally(() => setStarting(null));
  };
  // An answered question: what happened shows at the top, and the plan is read again (the show was checked again).
  const answered = (text: string) => { setNote(text); api.fixes(showLeft).then(setData).catch(() => undefined); refresh(); };
  const check = () => begin('check', api.checkFixes);
  const apply = () => { setAsking(false); begin('apply', () => api.applyFixes([...chosen])); };

  // One group of fixes, as a panel (DESIGN.md §1.11).
  const group = (g: (typeof GROUPS)[number]) => {
    const kinds = g.kinds.filter((k) => available.includes(k));
    if (!kinds.length) return null;
    return (
      <section key={g.id} id={g.id} className="panel" aria-labelledby={`${g.id}-h`} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <div className="panel-head" style={{ marginBottom: 4 }}><h2 id={`${g.id}-h`}>{g.title}</h2>
          <span className="num">{kinds.reduce((n, k) => n + (data!.fixes[k]?.count ?? 0), 0).toLocaleString('en-GB')}</span>
        </div>
        <ul className="rows">
          {kinds.map((k) => {
            const f = data!.fixes[k]!;
            return (
              <li key={k} style={{ flexDirection: 'column', alignItems: 'stretch', gap: 4 }}>
                <span className="actions" style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
                  <label className="choice" style={{ alignItems: 'center' }}>
                    <input type="checkbox" checked={chosen.has(k)} onChange={(e) => toggle(k, e.target.checked)} />
                    <strong>{FIX[k].title}</strong>
                  </label>
                  <span className="num">{f.count.toLocaleString('en-GB')}</span>
                </span>
                <span className="small muted">{FIX[k].what}</span>
                <details>
                  <summary className="small" style={{ cursor: 'pointer' }}>Which</summary>
                  <ul className="rows" style={{ marginTop: 4 }}>
                    {f.sample.map((x) => (
                      <li key={x.path}>
                        <span className={x.label ? 'small' : 'mono small'} title={libraryPath(x.path)} style={{ minWidth: 0, wordBreak: 'break-all' }}>{x.label ?? middle(libraryPath(x.path), 90)}</span>
                        <span className="small muted">{x.score ? `IMDb ${x.score[0].toFixed(1)}` : x.why ?? ''}</span>
                      </li>
                    ))}
                    {f.count > f.sample.length && <li><span className="small muted">and {(f.count - f.sample.length).toLocaleString('en-GB')} more</span></li>}
                  </ul>
                </details>
              </li>
            );
          })}
        </ul>
      </section>
    );
  };

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">Library health</p>
          <h1>Health</h1>
          <p className="lede">{data?.at ? `Checked ${when(data.at)} · daily` : 'Not checked yet'}</p>
        </div>
        <div className="actions">
          {!asking && <button className="btn btn-secondary btn-sm" type="button" aria-busy={starting === 'check'} onClick={check}>{data?.at ? 'Check again' : 'Check the library'}</button>}
          {!asking && (chosen.size > 0
            ? <button className="btn btn-primary" type="button" disabled={running} onClick={() => setAsking(true)}>Apply {count(total, 'fix', 'fixes')}</button>
            : <button className="btn btn-primary" type="button" aria-disabled="true" title="Choose fixes first">Apply fixes</button>)}
        </div>
      </header>

      {asking && (
        <section className="panel" role="group" aria-labelledby="ask-h" style={{ display: 'flex', flexDirection: 'column', gap: 12, borderColor: 'var(--mark)' }}>
          <h2 id="ask-h" style={{ margin: 0, fontSize: '1.15rem', fontWeight: 650 }}>Apply {count(total, 'fix', 'fixes')} to the library?</h2>
          <ul className="rows">{[...chosen].map((k) => <li key={k}><span>{FIX[k].title}</span><span className="num">{data?.fixes[k]?.count.toLocaleString('en-GB')}</span></li>)}</ul>
          <p className="hint">Nothing is overwritten or deleted: new files only where none exist, NFO changes with a copy of the old file, removals into quarantine. The whole run can be put back from History.</p>
          <div className="actions" style={{ justifyContent: 'flex-end' }}>
            <button className="btn btn-secondary" type="button" autoFocus onClick={() => setAsking(false)}>Cancel</button>
            <button className="btn btn-primary" type="button" onClick={apply}>Apply them</button>
          </div>
        </section>
      )}
      <JobError job={status?.job} />
      {!data && !error && <Loading label="Loading the library check" />}
      {error && <div className="banner banner-error" role="alert">{error}</div>}
      {note && <div className="banner banner-note" role="status">{note}</div>}
      {last && !running && status?.job?.name === 'fixes-apply' && (
        <div className={`banner ${last.failed.length ? 'banner-warn' : 'banner-note'}`} role="status" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
          <span className="status"><Dot kind={last.failed.length ? 'dot-warning' : 'dot-success'} />
            {Object.values(last.done).reduce((a, b) => a + (b ?? 0), 0)} fixed{last.failed.length ? `, ${last.failed.length} didn’t work` : ''}. What changed is in History.</span>
          {last.failed.slice(0, 8).map((f) => <span key={f.path} className="small">{libraryPath(f.path)}: {f.why}</span>)}
        </div>
      )}

      {data?.at && available.length === 0 && (
        <section className="panel" style={{ textAlign: 'center', padding: '32px 16px' }}>
          <h2 style={{ margin: '0 0 6px', fontSize: '1.2rem' }}>Nothing muthur can fix on its own</h2>
          <p className="hint">Anything left needs you; it’s under Questions for you.</p>
        </section>
      )}
      {group(GROUPS[0])}
      {group(GROUPS[1])}
      {data?.at && (Object.entries(data.manual).some(([, v]) => (v?.count ?? 0) > 0) || data.left > 0) && (
        <section id="questions" className="panel" aria-labelledby="manual-h" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div className="panel-head" style={{ marginBottom: 0 }}><h2 id="manual-h">{showLeft ? 'Left as is' : 'Questions for you'}</h2>
            {data.left > 0 || showLeft
              ? <button type="button" className="btn-link small" onClick={() => setShowLeft(!showLeft)}>{showLeft ? 'Show the open questions' : `Show the ${data.left} left as is`}</button>
              : null}
          </div>
          {!Object.values(data.manual).some((v) => (v?.count ?? 0) > 0) && (
            <p className="hint" style={{ margin: 0 }}>{showLeft ? 'Nothing is left as is.' : 'No open questions.'}</p>
          )}
          {Object.entries(data.manual).filter(([, v]) => (v?.count ?? 0) > 0).map(([k, v]) => (
            <details key={k}>
              <summary style={{ cursor: 'pointer' }}><strong>{QUESTIONS[k] ?? k}</strong> <span className="num muted">{v!.count}</span></summary>
              <ul className="rows" style={{ marginTop: 6 }}>
                {v!.items.map((q, i) => (
                  <li key={q.path + (q.season ?? '')} style={{ flexDirection: 'column', gap: 2 }}>
                    {/* A show's questions sit together: one 'leave all' per show, not on every row. */}
                    {!showLeft && showOf(q) && showOf(q) !== showOf(v!.items[i - 1]) && v!.items.filter((x) => showOf(x) === showOf(q)).length > 1 && (
                      <span className="actions" style={{ justifyContent: 'space-between' }}>
                        <strong>{showOf(q)!.slice(3)}</strong>
                        <button type="button" className="btn-link small" onClick={() => leave({ under: showOf(q)! })}>Leave all of {showOf(q)!.slice(3)} as is</button>
                      </span>
                    )}
                    <span className="mono small" style={{ wordBreak: 'break-all' }}>{libraryPath(q.path)}{q.season != null ? ` · season ${q.season}` : ''}</span>
                    <span className="small muted">{q.why}</span>
                    {(k === 'numbers' || k === 'seasons') && !showLeft
                      ? <EpisodeAnswers q={q} kind={k} onDone={answered} leave={() => leave({ items: [q] })} />
                      : (
                        <span className="actions">
                          <button type="button" className="btn-link small" onClick={() => leave({ items: [q], back: showLeft })}>{showLeft ? 'Ask again' : 'Leave as is'}</button>
                        </span>
                      )}
                    {(k === 'shows' || k === 'films') && (
                      <Chooser kind={k === 'shows' ? 'tv' : 'movie'} path={q.path} busy={running} onDone={answered} />
                    )}
                  </li>
                ))}
                {v!.count > v!.items.length && <li><span className="small muted">and {v!.count - v!.items.length} more</span></li>}
              </ul>
            </details>
          ))}
        </section>
      )}
      <DuplicatesPanel groups={dupGroups} />
      {group(GROUPS[2])}
      <QuarantinePanel busy={running} />
    </div>
  );
}
