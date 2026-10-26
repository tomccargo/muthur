import { useState } from 'react';
import { api, type Status } from '../api';
import { Dot, Spinner } from '../components';
import { when } from '../labels';

type Preview = { count: number; check: string; watched: number; resume: number; sample: string[] };

// The watched-status backup on the Dashboard: Kodi is the master, muthur keeps the history (§11).
export function WatchedPanel({ status, refresh }: { status: Status | null; refresh: () => void }) {
  const [message, setMessage] = useState<{ kind: 'error' | 'note'; text: string } | null>(null);
  const [working, setWorking] = useState<string | false>(false);  // which button's request runs
  const [accepting, setAccepting] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null);
  const w = status?.watched;
  const kodiSet = Boolean(status?.kodi);

  const run = (fn: () => Promise<unknown>, done: (r: never) => string, key = 'run') => {
    setMessage(null);
    setWorking(key);
    fn().then((r) => { setMessage({ kind: 'note', text: done(r as never) }); refresh(); })
      .catch((e: Error) => setMessage({ kind: 'error', text: e.message }))
      .finally(() => setWorking(false));
  };
  const look = () => {
    setMessage(null);
    setWorking('look');
    api.restorePreview().then(setPreview).catch((e: Error) => setMessage({ kind: 'error', text: e.message })).finally(() => setWorking(false));
  };

  return (
    <section className="panel" aria-labelledby="watched-h" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div className="panel-head" style={{ marginBottom: 0 }}><h2 id="watched-h">Watched status</h2></div>
      {w?.paused ? (
        <div className="banner banner-error" role="alert" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
          <strong>The backup stopped following Kodi.</strong>
          <span>{w.paused.why} That is what a lost or replaced Kodi database looks like, so muthur kept the last good state{w.last ? ` from ${when(w.last.at)}` : ''}.</span>
          {accepting ? (
            <>
              <span>Accept Kodi’s state as it is now? The backup then follows it again, and the items that turned unwatched are recorded as unwatched. The older history stays, so a restore to an earlier moment stays possible.</span>
              <div className="actions" style={{ justifyContent: 'flex-end' }}>
                <button className="btn btn-secondary btn-sm" type="button" autoFocus onClick={() => setAccepting(false)}>Cancel</button>
                <button className="btn btn-danger btn-sm" type="button" disabled={Boolean(working)}
                  aria-busy={working === 'accept'} onClick={() => { setAccepting(false); run(api.acceptWatched, () => 'The backup follows Kodi again.', 'accept'); }}>Accept Kodi’s state</button>
              </div>
            </>
          ) : (
            <div className="actions">
              <button className="btn btn-danger-outline btn-sm" type="button" onClick={() => setAccepting(true)}>Kodi’s state is right…</button>
              <span className="small">If Kodi lost its database, restore below instead.</span>
            </div>
          )}
        </div>
      ) : w?.last ? (
        <span className="status num"><Dot kind="dot-success" />Backed up {when(w.last.at)} · {w.last.watched.toLocaleString('en-GB')} of {w.last.items.toLocaleString('en-GB')} watched
          · {w.live ? 'live' : 'hourly'}</span>
      ) : (
        <span className="status"><Dot />{kodiSet ? 'Not backed up yet' : 'Needs the Kodi connection'}</span>
      )}

      {preview && (
        <div className="banner banner-warn" role="group" aria-label="Restore watched status" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
          {preview.count === 0 ? (
            <>
              <span>Kodi already has everything the backup has. Nothing to restore.</span>
              <div className="actions" style={{ justifyContent: 'flex-end' }}><button className="btn btn-secondary btn-sm" type="button" onClick={() => setPreview(null)}>Close</button></div>
            </>
          ) : (
            <>
              <strong>Restore {preview.count} {preview.count === 1 ? 'item' : 'items'} in Kodi?</strong>
              <span>
                {preview.watched > 0 && `${preview.watched} get their play count back. `}
                {preview.resume > 0 && `${preview.resume} get their resume point back. `}
                Nothing is lowered or marked unwatched.
              </span>
              <span className="small">{preview.sample.slice(0, 12).join(' · ')}{preview.count > 12 ? ` · and ${preview.count - 12} more` : ''}</span>
              <div className="actions" style={{ justifyContent: 'flex-end' }}>
                <button className="btn btn-secondary btn-sm" type="button" autoFocus onClick={() => setPreview(null)}>Cancel</button>
                <button className="btn btn-danger btn-sm" type="button" disabled={Boolean(working)} aria-busy={working === 'restore'} onClick={() => {
                  const check = preview.check;
                  setPreview(null);
                  run(() => api.restore(check), (r: { done: number; failed: number }) => `Restored ${r.done} in Kodi${r.failed ? `; ${r.failed} didn’t take, try again` : ''}.`, 'restore');
                }}>Restore {preview.count}</button>
              </div>
            </>
          )}
        </div>
      )}
      {message && <div className={`banner banner-${message.kind}`} role="alert">{message.text}</div>}
      <div className="actions">
        {/* A standing reason stays reachable: aria-disabled with the reason as its title (DESIGN.md §3). */}
        <button className="btn btn-secondary btn-sm" type="button" disabled={Boolean(working)} aria-busy={working === 'backup'}
          {...(!kodiSet ? { 'aria-disabled': true, title: 'Set up Kodi in Settings first' } : {})}
          onClick={kodiSet ? () => run(api.backupWatched, () => 'Backed up just now.', 'backup') : undefined}>Back up now</button>
        <button className="btn btn-danger-outline btn-sm" type="button" disabled={Boolean(working)} aria-busy={working === 'look'}
          {...(!kodiSet || !w?.last ? { 'aria-disabled': true, title: !kodiSet ? 'Set up Kodi in Settings first' : 'Nothing is backed up yet' } : {})}
          onClick={kodiSet && w?.last ? look : undefined}>Restore to Kodi…</button>
        {working === 'restore' && <span className="small"><Spinner /> Restoring in Kodi…</span>}
      </div>
    </section>
  );
}
