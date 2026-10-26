import { useState } from 'react';
import { WatchedPanel } from './Watched';
import { api, type PathState, type Status } from '../api';
import type { StatusHook } from '../App';
import { Dot, JobProgress, useElapsed } from '../components';
import { when } from '../labels';
import { Link } from '../nav';

// The Dashboard is numbers and status: what each panel means is in the docs and Settings, not repeated here.
// Problems keep their sentence and their way out (DESIGN.md §1.5); a panel with nothing to say is left out.

function pathProblem(label: string, p: PathState | undefined) {
  if (!p || (p.exists && p.readable)) return null;
  return <li key={label}><span>{label}</span><span className="status"><Dot kind="dot-danger" />{!p.exists ? 'Not found' : 'Can’t be read'}</span></li>;
}

export function Dashboard({ status, error, refresh }: StatusHook) {
  const [message, setMessage] = useState<{ kind: 'error' | 'note'; text: string } | null>(null);
  const [kodiNote, setKodiNote] = useState<{ kind: 'error' | 'note'; text: string } | null>(null);
  const [waking, setWaking] = useState(false);
  const counts = status?.inbox.counts ?? {};
  const job = status?.job;
  const tmdb = Boolean(status?.tmdb.configured);

  // A job started while another runs waits its turn (the queue), so nothing here is disabled for being busy.
  const [starting, setStarting] = useState<string | null>(null);
  const start = (key: string, fn: () => Promise<unknown>) => {
    setMessage(null);
    setStarting(key);
    fn().then(refresh).catch((e: Error) => setMessage({ kind: 'error', text: e.message })).finally(() => setStarting(null));
  };
  const wakeFor = useElapsed(waking);

  const scanned = status?.inbox.scannedAt;
  const waiting = (counts.ready ?? 0) + (counts.review ?? 0);
  const k = status?.kodi;
  const sc = status?.scores;
  const device = status?.names.device ?? 'Kodi device';
  const suspicious = counts.suspicious ?? 0;
  const folderProblems = [pathProblem('Finished downloads', status?.paths.downloads), pathProblem('TV', status?.paths.tv),
    pathProblem('Film', status?.paths.film)].filter(Boolean);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">{status?.names.nas ?? 'NAS'}</p>
          <h1>Dashboard</h1>
          <p className="lede">{scanned ? `${waiting} to file · checked ${when(scanned)}` : 'Downloads not checked yet'}</p>
        </div>
        <div className="actions">
          {tmdb
            ? <button className="btn btn-primary" type="button" aria-busy={starting === 'scan'} onClick={() => start('scan', api.scan)} title="Looks in the downloads folder and works out what each one is. Nothing moves.">Look for new downloads</button>
            : <button className="btn btn-primary" type="button" aria-disabled="true" title="Add the TMDB token in Settings first">Look for new downloads</button>}
        </div>
      </header>

      {status && <SetupChecklist status={status} />}
      {error && <div className="banner banner-error" role="alert">muthur isn’t answering: {error}</div>}
      {message && <div className={`banner banner-${message.kind}`} role="alert">{message.text}</div>}
      {suspicious > 0 && (
        <div className="banner banner-error" role="alert">
          <span><strong>{suspicious} suspicious download{suspicious === 1 ? '' : 's'}</strong> — don’t open {suspicious === 1 ? 'it' : 'them'}.</span>
          <Link to="/inbox?show=suspicious">See which</Link>
        </div>
      )}
      {status && !status.applying && (
        <div className="banner banner-note">
          <span className="status"><Dot kind="dot-warning" />Dry run is on: nothing changes.</span>
          <Link to="/settings">Settings</Link>
        </div>
      )}
      <JobProgress job={job} queue={status?.queue} />

      <section className="tiles" aria-label="Downloads">
        <Link className="tile" to="/inbox?show=ready"><span className="label">Ready</span><strong>{counts.ready ?? 0}</strong></Link>
        <Link className="tile" to="/inbox?show=review"><span className="label">Needs you</span><strong>{counts.review ?? 0}</strong></Link>
        <Link className="tile" to="/inbox?show=waiting"><span className="label">Downloading</span><strong>{counts.waiting ?? 0}</strong></Link>
        {(counts.packed ?? 0) > 0 && <Link className="tile" to="/inbox?show=packed"><span className="label">Packed</span><strong>{counts.packed}</strong></Link>}
        <Link className="tile" to="/inbox?show=ignored"><span className="label">Ignored</span><strong>{counts.ignored ?? 0}</strong></Link>
      </section>

      <div className="grid-2">
        <section className="panel" aria-labelledby="kodi-h">
          <div className="panel-head"><h2 id="kodi-h">Kodi on the {device}</h2><Link to="/settings" className="small">Settings</Link></div>
          <p style={{ margin: '0 0 12px' }}>
            {k == null ? <span className="status"><Dot />Not set up</span>
              : k.connected ? <span className="status"><Dot kind="dot-success" />Connected · Kodi {k.version}</span>
                : <span className="status"><Dot kind="dot-danger" />{k.off ? 'Off (asleep, or Kodi closed)' : k.problem}</span>}
          </p>
          <div className="actions">
            {k && !k.connected && k.canWake && (
              <button className="btn btn-secondary btn-sm" type="button" disabled={waking} aria-busy={waking} onClick={() => {
                setKodiNote(null);
                setWaking(true);
                api.wakeShield()
                  .then(() => { setKodiNote({ kind: 'note', text: `The ${device} is awake and Kodi answers.` }); refresh(); })
                  .catch((e: Error) => setKodiNote({ kind: 'error', text: e.message }))
                  .finally(() => setWaking(false));
              }}>{waking ? `Waking the ${device}…${wakeFor}` : `Wake the ${device}`}</button>
            )}
            {k?.connected && (
              <button className="btn btn-secondary btn-sm" type="button" onClick={() => {
                setKodiNote(null);
                api.scanKodi()
                  .then(() => setKodiNote({ kind: 'note', text: 'Kodi is looking for new files.' }))
                  .catch((e: Error) => setKodiNote({ kind: 'error', text: e.message }));
              }}>Ask Kodi to look for new files</button>
            )}
          </div>
          {k?.pendingScan && <p className="hint" style={{ margin: '10px 0 0' }}>The last Apply waits for Kodi ({when(k.pendingScan)}).</p>}
          {kodiNote && <div className={`banner banner-${kodiNote.kind}`} role="alert" style={{ marginTop: 10 }}>{kodiNote.text}</div>}
        </section>

        <section className="panel" aria-labelledby="mem-h">
          <div className="panel-head"><h2 id="mem-h">Known shows</h2></div>
          <p style={{ margin: '0 0 12px' }}>
            <strong className="num" style={{ fontFamily: 'var(--font-display)', fontSize: '1.4rem' }}>{status?.memory.shows ?? 0}</strong>
            <span className="muted"> · their new episodes go straight to their folder</span>
          </p>
          <div className="actions">
            {tmdb
              ? <button className="btn btn-secondary btn-sm" type="button" aria-busy={starting === 'learn'} onClick={() => start('learn', api.learnShows)}
                title="Reads the TV folder and matches each show to TMDB, so new episodes find their folder. Changes no files.">Read the TV folder</button>
              : <button className="btn btn-secondary btn-sm" type="button" aria-disabled="true" title="Add the TMDB token in Settings first">Read the TV folder</button>}
            <span className="small muted">changes nothing</span>
          </div>
        </section>

        <WatchedPanel status={status} refresh={refresh} />

        <section className="panel" aria-labelledby="lib-h">
          <div className="panel-head"><h2 id="lib-h">Library</h2></div>
          <LibraryProblems status={status} />
        </section>

        <section className="panel" aria-labelledby="scores-h">
          <div className="panel-head"><h2 id="scores-h">IMDb scores</h2></div>
          <div className="actions" style={{ justifyContent: 'space-between' }}>
            <span className="num">{sc?.refreshed
              ? `Updated ${when(sc.refreshed)} · ${sc.ratings.toLocaleString('en-GB')} scores · next ${when(sc.next)}`
              : 'Not downloaded yet · weekly'}</span>
            {tmdb
              ? <button className="btn btn-secondary btn-sm" type="button" aria-busy={starting === 'scores'} onClick={() => start('scores', api.refreshScores)}>Refresh now</button>
              : <button className="btn btn-secondary btn-sm" type="button" aria-disabled="true" title="Add the TMDB token in Settings first">Refresh now</button>}
          </div>
        </section>

        {folderProblems.length > 0 && (
          <section className="panel" aria-labelledby="dirs-h">
            <div className="panel-head"><h2 id="dirs-h">Folders</h2><Link to="/settings" className="small">Settings</Link></div>
            <ul className="rows">{folderProblems}</ul>
          </section>
        )}
      </div>
    </div>
  );
}

// Until the essentials are set up, the Dashboard says what's left; each step ticks itself and links to
// where it's done. An install that is set up never sees it.
function SetupChecklist({ status }: { status: Status }) {
  const k = status.kodi;
  const folder = (p: string) => p.replace(/[/\\]+$/, '').split(/[/\\]/).pop() ?? p;
  const sources = k && k.connected ? k.sources : undefined;
  const steps: { done: boolean; text: string; to: string; optional?: boolean; pending?: string }[] = [
    { done: status.tmdb.configured, text: 'Add your TMDB token', to: '/settings' },
    { done: Boolean(k), text: 'Connect Kodi', to: '/settings' },
    { done: Boolean(sources?.tv && sources?.film), to: '/settings', pending: sources ? undefined : 'checked when Kodi answers',
      text: `Kodi has video sources for the ${folder(status.paths.tv.path)} and ${folder(status.paths.film.path)} folders` },
    { done: Boolean(status.inbox.scannedAt), text: 'Check the downloads for the first time', to: '/inbox' },
    { done: Boolean(k?.canWake), text: `Optional: let muthur wake the ${status.names.device}`, to: '/settings', optional: true },
  ];
  const needed = steps.filter((s) => !s.optional && !(s.pending && !s.done));
  if (needed.every((s) => s.done) && !(sources && !(sources.tv && sources.film))) return null;
  return (
    <section className="panel" aria-labelledby="setup-h">
      <div className="panel-head"><h2 id="setup-h">Getting started</h2><span className="small muted">{steps.filter((s) => s.done).length} of {steps.length} done</span></div>
      <ul className="rows">
        {steps.map((s) => (
          <li key={s.text}>
            <span className="status"><Dot kind={s.done ? 'dot-success' : ''} />{s.done ? s.text : <Link to={s.to}>{s.text}</Link>}</span>
            {!s.done && s.pending && <span className="small muted">{s.pending}</span>}
          </li>
        ))}
      </ul>
    </section>
  );
}

// What's wrong in the library, each kind a tile that opens where it's fixed. Only kinds with something in them.
function LibraryProblems({ status }: { status: Status | null }) {
  const l = status?.library ?? {};
  const tiles: [string, number | undefined, string][] = [
    ['Shows without IMDb scores', l.imdbData, '/health'],
    ['Scores to add', l.scores, '/health'],
    ['NFOs to write', l.nfos, '/health'],
    ['Duplicates', status?.duplicatesAt ? status.duplicates : undefined, '/duplicates'],
    ['Questions', l.questions, '/health'],
    ['Leftovers', l.leftovers, '/health'],
  ];
  const shown = tiles.filter(([, n]) => (n ?? 0) > 0);
  if (!shown.length) {
    return <span className="status"><Dot kind="dot-success" />{status?.duplicatesAt ? 'In order' : 'In order · duplicates not checked yet'}</span>;
  }
  return (
    <div className="tiles inset">
      {shown.map(([label, n, to]) => (
        <Link key={label} className="tile" to={to}><span className="label">{label}</span><strong>{(n ?? 0).toLocaleString('en-GB')}</strong></Link>
      ))}
    </div>
  );
}
