import { useEffect, useRef, useState } from 'react';
import { api, type Settings, type UpdateState } from '../api';
import { Dot } from '../components';
import { count, when } from '../labels';

// What the last Apply did in Download Station (Settings, Download Station).
export function CleanUp({ last }: { last: Settings['downloadStation']['lastCleanUp'] }) {
  if (!last) return <p className="hint">No clean-up yet: it runs after the next download is filed.</p>;
  if (last.problem) return <p className="status small"><Dot kind="dot-danger" />Last clean-up, {when(last.at)}: {last.problem}</p>;
  const removed = last.removed?.length ?? 0, left = last.notFinished?.length ?? 0;
  return (
    <p className="status small"><Dot kind="dot-success" />Last clean-up, {when(last.at)}: {count(removed, 'task')} removed
      {left ? `, ${count(left, 'task')} left because Download Station hadn’t finished ${left === 1 ? 'it' : 'them'}` : ''}.</p>
  );
}

const BUSY = new Set(['pulling', 'pulled', 'rebuilding']);

function describe(u: UpdateState): { dot: string; text: string } | null {
  switch (u.state) {
    case 'pulling': return { dot: 'dot-warning', text: 'Downloading the newest muthur…' };
    case 'pulled': return { dot: 'dot-warning', text: u.waitingForIdle ? 'Downloaded. It is installed once the current job is done.' : 'Downloaded; installing…' };
    case 'rebuilding': return { dot: 'dot-warning', text: 'Container Manager is restarting muthur with the new version; this page is back in a minute or two.' };
    case 'current': return { dot: 'dot-success', text: `Up to date (checked ${when(u.at)}).` };
    case 'done': return { dot: 'dot-success', text: `Updated ${when(u.at)}.` };
    case 'failed': return { dot: 'dot-danger', text: u.problem ?? 'The update failed.' };
    default: return u.problem ? { dot: 'dot-danger', text: u.problem } : null;
  }
}

// Settings, muthur: the version, and updating it through the relay container (docs/DEPLOY.md §5).
export function UpdateSettings() {
  const [u, setU] = useState<UpdateState | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const first = useRef<string | null>(null);

  useEffect(() => {
    let stop = false;
    let timer: number | undefined;
    const look = () => {
      api.update().then((next) => {
        if (stop) return;
        first.current ??= next.version;
        if (next.version !== first.current) { window.location.reload(); return; }
        setU(next);
        if (next.state && BUSY.has(next.state)) timer = window.setTimeout(look, 3000);
      }).catch(() => { if (!stop) timer = window.setTimeout(look, 5000); }); // muthur is restarting
    };
    look();
    return () => { stop = true; window.clearTimeout(timer); };
  }, [u?.state]);

  const start = () => {
    setProblem(null);
    api.startUpdate().then(setU).catch((e: Error) => setProblem(e.message));
  };

  const line = u && describe(u);
  const running = !!u?.state && BUSY.has(u.state);
  return (
    <section className="panel form" aria-labelledby="update-h">
      <h2 id="update-h" style={{ margin: 0, fontSize: '1.15rem', fontWeight: 650 }}>muthur {u ? u.version : ''}</h2>
      {u && !u.possible && (
        <p className="hint">Update in Container Manager, or over SSH (docs/DEPLOY.md §5). With muthur’s relay container running, you can update from here.</p>
      )}
      {u?.possible && <>
        <p className="hint">Downloads the newest muthur and has Container Manager restart it. A job that is running is finished first.</p>
        <div className="actions">
          <button className="btn btn-secondary btn-sm" type="button" onClick={start} disabled={running} aria-busy={running}>
            {running ? 'Updating…' : 'Update muthur'}
          </button>
          {line && <span className="status small" role="status"><Dot kind={line.dot} />{line.text}</span>}
        </div>
      </>}
      {problem && <p className="status small" role="alert"><Dot kind="dot-danger" />{problem}</p>}
    </section>
  );
}
