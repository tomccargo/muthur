import { useEffect, useState } from 'react';
import { QuarantinePanel } from './Quarantine';
import { TitleCard } from './Review';
import type { Card, Kind } from '../api';
import { api, type FixKind, type FixResult, type Fixes, type Question } from '../api';
import type { StatusHook } from '../App';
import { Dot, JobError, Loading } from '../components';
import { libraryPath, middle, when } from '../labels';

// What each fix does to the reader's files (DESIGN.md §1.7: name what happens, not the record).
const FIX: Record<FixKind, { title: string; what: string }> = {
  'imdb-data': { title: 'Download IMDb scores for shows that have none yet', what: 'Then muthur’s own NFOs get their scores; other NFOs follow as “Add IMDb scores”.' },
  'imdb-scores': { title: 'Add IMDb scores to NFOs', what: 'Adds IMDb’s score as the one Kodi shows. Other ratings in the NFO stay; a copy of each old NFO is kept. Kodi re-reads each item.' },
  'episode-nfos': { title: 'Write NFOs for episodes that have none', what: 'Writes an NFO (and a thumbnail where missing) from TMDB, with IMDb’s score. Only for seasons TMDB numbers the way your library does.' },
  'show-nfos': { title: 'Write tvshow.nfo for show folders that have none', what: 'Writes the show’s NFO, poster, fanart and logo from TMDB where they’re missing.' },
  'film-nfos': { title: 'Write NFOs for films that have none', what: 'Writes the NFO, poster, fanart and logo from TMDB where missing, for films muthur recognises with certainty by name, year and length.' },
  renames: { title: 'Rename episodes to the library’s naming', what: 'Show - S01E02 - TMDB’s title, with the NFO, thumbnail and subtitles. Only while Kodi is on: it keeps each episode’s watched status.' },
  posters: { title: 'Replace missing and poor posters', what: 'TMDB’s poster where there is none, or one under 500 pixels wide or not poster-shaped. The old one is kept; Kodi re-reads each item.' },
  subtitles: { title: 'Put subtitles where Kodi finds them', what: 'English and Dutch go beside the video under its name; other languages and extra copies go to quarantine.' },
  leftovers: { title: 'Move leftover files to quarantine', what: 'Tracker notes, Thumbs.db, and NFOs, thumbnails or subtitles of videos that are gone.' },
  'empty-films': { title: 'Move film folders without a video to quarantine', what: 'Folders that only hold an NFO or artwork.' },
};
const ORDER: FixKind[] = ['imdb-data', 'imdb-scores', 'episode-nfos', 'show-nfos', 'film-nfos', 'posters', 'subtitles', 'renames', 'leftovers', 'empty-films'];
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
      .then((r) => onDone(`${picked.title}${picked.year ? ` (${picked.year})` : ''}: ${Object.values(r.fixes).reduce((a, b) => a + (b ?? 0), 0)} fixes added${r.questions ? `, ${r.questions} questions left` : ''}.`))
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

  useEffect(() => {
    api.fixes(showLeft).then((d) => { setData(d); setChosen(new Set()); }).catch((e: Error) => setError(e.message));
    api.fixesLast().then((r) => setLast('done' in r ? (r as FixResult) : null)).catch(() => undefined);
  }, [running, status?.job?.finished, showLeft]);

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
  const check = () => begin('check', api.checkFixes);
  const apply = () => { setAsking(false); begin('apply', () => api.applyFixes([...chosen])); };

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
            ? <button className="btn btn-primary" type="button" disabled={running} onClick={() => setAsking(true)}>Apply {total.toLocaleString('en-GB')} fixes</button>
            : <button className="btn btn-primary" type="button" aria-disabled="true" title="Choose fixes first">Apply fixes</button>)}
        </div>
      </header>

      {asking && (
        <section className="panel" role="group" aria-labelledby="ask-h" style={{ display: 'flex', flexDirection: 'column', gap: 12, borderColor: 'var(--mark)' }}>
          <h2 id="ask-h" style={{ margin: 0, fontSize: '1.15rem', fontWeight: 650 }}>Apply {total.toLocaleString('en-GB')} fixes to the library?</h2>
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
          <p className="hint">Anything left needs you; it’s listed below.</p>
        </section>
      )}
      {available.map((k) => {
        const f = data!.fixes[k]!;
        return (
          <section key={k} className="panel" style={{ display: 'flex', flexDirection: 'column', gap: 8, borderColor: chosen.has(k) ? 'var(--mark)' : undefined }}>
            <div className="panel-head" style={{ marginBottom: 0 }}>
              <label className="choice" style={{ alignItems: 'center' }}>
                <input type="checkbox" checked={chosen.has(k)} onChange={(e) => toggle(k, e.target.checked)} />
                <h2 style={{ fontSize: '1.1rem' }}>{FIX[k].title}</h2>
              </label>
              <span className="num">{f.count.toLocaleString('en-GB')}</span>
            </div>
            <ul className="rows">
              {f.sample.map((x) => (
                <li key={x.path}>
                  <span className={x.label ? 'small' : 'mono small'} title={libraryPath(x.path)} style={{ minWidth: 0, wordBreak: 'break-all' }}>{x.label ?? middle(libraryPath(x.path), 90)}</span>
                  <span className="small muted">{x.score ? `IMDb ${x.score[0].toFixed(1)}` : x.why ?? ''}</span>
                </li>
              ))}
              {f.count > f.sample.length && <li><span className="small muted">and {(f.count - f.sample.length).toLocaleString('en-GB')} more</span></li>}
            </ul>
          </section>
        );
      })}

      {data?.at && (Object.entries(data.manual).some(([, v]) => (v?.count ?? 0) > 0) || data.left > 0) && (
        <section className="panel" aria-labelledby="manual-h" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div className="panel-head" style={{ marginBottom: 0 }}><h2 id="manual-h">{showLeft ? 'Left as is' : 'Needs you'}</h2>
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
                    <span className="actions">
                      <button type="button" className="btn-link small" onClick={() => leave({ items: [q], back: showLeft })}>{showLeft ? 'Ask again' : 'Leave as is'}</button>
                    </span>
                    {(k === 'shows' || k === 'films') && (
                      <Chooser kind={k === 'shows' ? 'tv' : 'movie'} path={q.path} busy={running}
                        onDone={(text) => { setNote(text); api.fixes().then(setData).catch(() => undefined); refresh(); }} />
                    )}
                  </li>
                ))}
                {v!.count > v!.items.length && <li><span className="small muted">and {v!.count - v!.items.length} more</span></li>}
              </ul>
            </details>
          ))}
        </section>
      )}
      <QuarantinePanel busy={running} />
    </div>
  );
}
