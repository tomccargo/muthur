import { useState } from 'react';
import { api, type PathState } from '../api';
import type { StatusHook } from '../App';
import { Dot, Footer, JobProgress } from '../components';
import { when } from '../labels';
import { Link } from '../nav';

function pathLine(label: string, p: PathState | undefined, needWrite: boolean) {
  if (!p) return null;
  const ok = p.exists && p.readable;
  const text = !p.exists ? 'Not found' : !p.readable ? "Can't be read" : needWrite && !p.writable ? 'Read only for now' : 'Ready';
  return (
    <li key={label}>
      <span>{label}</span>
      <span className="status"><Dot kind={ok ? 'dot-success' : 'dot-danger'} />{text}</span>
    </li>
  );
}

export function Dashboard({ status, error, refresh }: StatusHook) {
  const [message, setMessage] = useState<{ kind: 'error' | 'note'; text: string } | null>(null);
  const counts = status?.inbox.counts ?? {};
  const job = status?.job;
  const busy = Boolean(job?.running);

  const start = (fn: () => Promise<unknown>) => {
    setMessage(null);
    fn().then(refresh).catch((e: Error) => setMessage({ kind: 'error', text: e.message }));
  };

  const scanned = status?.inbox.scannedAt;
  const waiting = (counts.ready ?? 0) + (counts.review ?? 0);
  const k = status?.kodi;
  const sc = status?.scores;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">Nostromo</p>
          <h1>Dashboard</h1>
          <p className="lede">
            {scanned ? `${waiting} download${waiting === 1 ? '' : 's'} to file · checked ${when(scanned)}` : 'The downloads haven’t been checked yet.'}
          </p>
        </div>
        <div className="actions">
          <button className="btn btn-primary" type="button" disabled={busy || !status?.tmdb.configured} onClick={() => start(api.scan)}>
            Check downloads
          </button>
        </div>
      </header>

      {error && <div className="banner banner-error" role="alert">muthur isn’t answering: {error}</div>}
      {message && <div className={`banner banner-${message.kind}`} role="alert">{message.text}</div>}
      {status && !status.tmdb.configured && (
        <div className="banner banner-warn">muthur needs a TMDB token to recognise titles. <Link to="/settings">Add it in Settings</Link></div>
      )}
      {(counts.suspicious ?? 0) > 0 && (
        <div className="banner banner-error" role="alert">
          <span>
            <strong>{counts.suspicious} download{counts.suspicious === 1 ? ' is' : 's are'} a program named like an episode or film.</strong>{' '}
            Don’t open {counts.suspicious === 1 ? 'it' : 'them'}: this is a common way malware spreads. muthur leaves {counts.suspicious === 1 ? 'it' : 'them'} alone.
          </span>
          <Link to="/inbox?show=suspicious">See which</Link>
        </div>
      )}
      {status && !status.applying && (
        <div className="banner banner-note">
          <span className="status"><Dot kind="dot-warning" />For now muthur only plans: it shows where every download would go, and moves nothing.</span>
        </div>
      )}
      <JobProgress job={job} />

      <section className="tiles" aria-label="Downloads">
        <Link className="tile" to="/inbox?show=ready"><span className="label">Ready</span><strong>{counts.ready ?? 0}</strong><span className="sub">matched with confidence</span></Link>
        <Link className="tile" to="/inbox?show=review"><span className="label">Needs you</span><strong>{counts.review ?? 0}</strong><span className="sub">not certain enough to file</span></Link>
        <Link className="tile" to="/inbox?show=waiting"><span className="label">Still downloading</span><strong>{counts.waiting ?? 0}</strong><span className="sub">changed in the last 10 minutes</span></Link>
        {(counts.packed ?? 0) > 0 && (
          <Link className="tile" to="/inbox?show=packed"><span className="label">Packed</span><strong>{counts.packed}</strong><span className="sub">in an archive; muthur doesn’t unpack</span></Link>
        )}
        <Link className="tile" to="/inbox?show=ignored"><span className="label">Ignored</span><strong>{counts.ignored ?? 0}</strong><span className="sub">not video; left alone</span></Link>
      </section>

      <div className="grid-2">
        <section className="panel" aria-labelledby="kodi-h">
          <div className="panel-head"><h2 id="kodi-h">Kodi on the Shield</h2><Link to="/settings" className="small">Settings</Link></div>
          <ul className="rows" style={{ marginBottom: 12 }}>
            <li>
              <span>Connection</span>
              {k == null ? <span className="status"><Dot />Not set up yet</span>
                : k.connected ? <span className="status"><Dot kind="dot-success" />Connected · Kodi {k.version}</span>
                  : <span className="status"><Dot kind="dot-danger" />{k.problem}</span>}
            </li>
          </ul>
          {k?.connected ? (
            <button className="btn btn-secondary btn-sm" type="button" onClick={() => {
              setMessage(null);
              api.scanKodi()
                .then(() => setMessage({ kind: 'note', text: 'Kodi is looking for new files now. New episodes show up in its library in a minute or two.' }))
                .catch((e: Error) => setMessage({ kind: 'error', text: e.message }));
            }}>Ask Kodi to look for new files</button>
          ) : (
            <p className="hint">muthur asks Kodi to look for new files after every Apply, once the connection is set up.</p>
          )}
        </section>

        <section className="panel" aria-labelledby="mem-h">
          <div className="panel-head"><h2 id="mem-h">Shows muthur knows</h2></div>
          <p style={{ margin: '0 0 12px', fontSize: 14 }}>
            <strong className="num" style={{ fontFamily: 'var(--font-display)', fontSize: '1.4rem' }}>{status?.memory.shows ?? 0}</strong> shows remembered.
            New episodes of a remembered show go straight into its folder, without a search.
          </p>
          <p className="hint" style={{ marginBottom: 12 }}>
            Learning reads your TV folder and checks each show against TMDB. A show whose NFO disagrees with what muthur finds is not remembered.
          </p>
          <button className="btn btn-secondary btn-sm" type="button" disabled={busy || !status?.tmdb.configured} onClick={() => start(api.learnShows)}>
            Learn shows from the library
          </button>
        </section>

        <section className="panel" aria-labelledby="scores-h">
          <div className="panel-head"><h2 id="scores-h">IMDb scores</h2></div>
          {sc?.refreshed ? (
            <ul className="rows" style={{ marginBottom: 12 }}>
              <li><span>Downloaded from IMDb</span><span>{when(sc.refreshed)}</span></li>
              <li><span>Kept for your library</span><span className="num">{sc.ratings.toLocaleString('en-GB')} scores · {sc.episodes.toLocaleString('en-GB')} episodes</span></li>
              <li><span>Next refresh</span><span>{when(sc.next)}</span></li>
              {sc.checked != null && <li><span>Last refresh</span><span className="num">{sc.updated} of {sc.checked} muthur NFOs updated</span></li>}
            </ul>
          ) : (
            <p className="hint" style={{ marginBottom: 12 }}>
              Not downloaded yet. Once a week muthur reads IMDb’s public datasets (about 64 MB, personal use only) and keeps the scores of what’s in your library.
            </p>
          )}
          <p className="hint" style={{ marginBottom: 12 }}>
            IMDb’s score is the one Kodi shows. An episode only gets one when IMDb and TMDB number its season the same way; otherwise TMDB’s score stays.
          </p>
          <button className="btn btn-secondary btn-sm" type="button" disabled={busy || !status?.tmdb.configured} onClick={() => start(api.refreshScores)}>
            Refresh scores now
          </button>
        </section>

        <section className="panel" aria-labelledby="dirs-h">
          <div className="panel-head"><h2 id="dirs-h">Folders</h2></div>
          <ul className="rows">
            {pathLine('Finished downloads', status?.paths.downloads, false)}
            {pathLine('TV', status?.paths.tv, false)}
            {pathLine('Film', status?.paths.film, false)}
          </ul>
        </section>
      </div>
      <Footer />
    </div>
  );
}
