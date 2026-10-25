import { useEffect, useState } from 'react';
import { api, type Op, type Run } from '../api';
import type { StatusHook } from '../App';
import { Dot, Footer, JobProgress } from '../components';
import { libraryPath, middle, size, splitId, when } from '../labels';

const VERB: Record<Op['op'], string> = { move: 'Moved', write: 'Wrote', quarantine: 'Quarantined', mkdir: 'Made folder', update: 'New scores in' };

function Ops({ run }: { run: Run }) {
  const [ops, setOps] = useState<Op[] | null>(null);
  useEffect(() => { api.run(run.id).then((r) => setOps(r.ops)).catch(() => setOps([])); }, [run.id, run.undone]);
  if (!ops) return <p className="hint">Loading…</p>;
  const shown = ops.filter((o) => o.op !== 'mkdir');
  return (
    <ul className="rows" style={{ marginTop: 8 }}>
      {shown.map((o) => (
        <li key={o.id} style={{ flexDirection: 'column', gap: 2 }}>
          <span className="status small">
            <Dot kind={o.status === 'done' ? (o.op === 'quarantine' ? 'dot-warning' : 'dot-success') : ''} />
            {o.status === 'undone' ? `${VERB[o.op]}, then put back` : o.status === 'failed' ? `${VERB[o.op]}: didn’t happen` : VERB[o.op]}
            {o.size ? <span className="muted">· {size(o.size)}</span> : null}
          </span>
          {o.src && o.op !== 'update' && <span className="mono small muted" style={{ wordBreak: 'break-all' }}>{libraryPath(o.src)}</span>}
          <span className="mono small" style={{ wordBreak: 'break-all', textDecoration: o.status === 'undone' ? 'line-through' : undefined }}>
            {o.src && o.op !== 'update' ? '→ ' : ''}{libraryPath(o.dst)}
          </span>
          {o.error && <span className="small" style={{ color: 'var(--warn-text)' }}>Not put back: {o.error}</span>}
        </li>
      ))}
    </ul>
  );
}

function RunCard({ run, busy, onUndo }: { run: Run; busy: boolean; onUndo: () => void }) {
  const [open, setOpen] = useState(false);
  const [asking, setAsking] = useState(false);
  const s = run.summary;
  const stopped = s?.items.filter((i) => !i.ok) ?? [];
  return (
    <section className="panel" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div className="panel-head" style={{ marginBottom: 0 }}>
        <h2>{new Date(run.started * 1000).toDateString() === new Date().toDateString() ? `Today, ${when(run.started)}` : when(run.started)}</h2>
        <span className="status small">
          {run.undone ? <><Dot />Put back {when(run.undone)}</>
            : run.kind === 'scores' ? <><Dot kind="dot-success" />IMDb scores</>
              : run.kind === 'library' ? <><Dot kind="dot-success" />Library edit</>
              : <><Dot kind="dot-success" />{s?.applied ?? 0} applied{stopped.length ? `, ${stopped.length} stopped` : ''}</>}
        </span>
      </div>
      <p className="hint" style={{ margin: 0 }}>
        {run.kind === 'library'
          ? `${(run.summary as unknown as { label?: string } | null)?.label ?? 'A library edit'} · ${run.counts.update + run.counts.write} file${run.counts.update + run.counts.write === 1 ? '' : 's'} written; the old ones are kept for putting back`
          : run.kind === 'scores'
          ? `${run.counts.update} NFO${run.counts.update === 1 ? '' : 's'} got new IMDb scores; the old files are kept for putting back`
          : `${run.counts.move} file${run.counts.move === 1 ? '' : 's'} moved · ${run.counts.write} written · ${run.counts.quarantine} to quarantine`}
      </p>
      {stopped.length > 0 && (
        <ul className="rows">
          {stopped.map((i) => (
            <li key={i.id} style={{ flexDirection: 'column', gap: 2 }}>
              <span className="mono small">{middle(splitId(i.id).name, 60)}</span>
              <span className="small" style={{ color: 'var(--warn-text)' }}>{i.why}</span>
            </li>
          ))}
        </ul>
      )}
      {asking && (
        <div className="banner banner-warn" role="group" aria-label="Put this run back" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
          <strong>Put everything from this run back?</strong>
          <span>
            {run.kind === 'scores'
              ? `The ${run.counts.update} NFO${run.counts.update === 1 ? '' : 's'} get their earlier scores back. A file changed since then is left alone and listed.`
              : run.kind === 'health'
              ? `The ${run.counts.quarantine} quarantined file${run.counts.quarantine === 1 ? '' : 's'} come back, the ${run.counts.write} file${run.counts.write === 1 ? '' : 's'} muthur wrote are removed and ${run.counts.update} NFO${run.counts.update === 1 ? '' : 's'} get their old content. A file changed since then is left alone and listed.`
              : run.kind === 'duplicates'
              ? `The ${run.counts.quarantine} quarantined file${run.counts.quarantine === 1 ? '' : 's'} come back and the ${run.counts.move} renamed one${run.counts.move === 1 ? '' : 's'} get their old names. Kodi sees it after its next scan. A file changed since then is left alone and listed.`
              : `The ${run.counts.move} moved file${run.counts.move === 1 ? '' : 's'} go back to the downloads folder, the ${run.counts.write} file${run.counts.write === 1 ? '' : 's'} muthur wrote are removed, and quarantined leftovers return. A file changed since then is left alone and listed.`}
          </span>
          <div className="actions" style={{ justifyContent: 'flex-end' }}>
            <button className="btn btn-secondary btn-sm" type="button" autoFocus onClick={() => setAsking(false)}>Cancel</button>
            <button className="btn btn-danger btn-sm" type="button" onClick={() => { setAsking(false); onUndo(); }}>Put it back</button>
          </div>
        </div>
      )}
      <div className="actions">
        <button className="btn btn-secondary btn-sm" type="button" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? 'Hide the changes' : 'Show the changes'}</button>
        {!run.undone && !asking && (
          <button className="btn btn-danger-outline btn-sm" type="button" disabled={busy} onClick={() => setAsking(true)}>
            Put this run back…
          </button>
        )}
      </div>
      {open && <Ops run={run} />}
    </section>
  );
}

export function HistoryPage({ status, refresh }: StatusHook) {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const running = Boolean(status?.job?.running);

  useEffect(() => {
    api.history().then((h) => setRuns(h.runs)).catch((e: Error) => setMessage(e.message));
  }, [running, status?.inbox.scannedAt]);

  const undo = (id: number) => {
    setMessage(null);
    api.undo(id).then(refresh).catch((e: Error) => setMessage(e.message));
  };

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">History</p>
          <h1>What muthur did</h1>
          <p className="lede">Every run and every file it touched. A run can be put back as a whole.</p>
        </div>
      </header>
      {message && <div className="banner banner-error" role="alert">{message}</div>}
      <JobProgress job={status?.job} queue={status?.queue} />
      {runs && runs.length === 0 && (
        <section className="panel" style={{ textAlign: 'center', padding: '40px 16px' }}>
          <h2 style={{ margin: '0 0 6px', fontSize: '1.2rem' }}>Nothing yet</h2>
          <p className="hint">When downloads are applied from the Inbox, each run shows up here.</p>
        </section>
      )}
      {runs?.map((r) => <RunCard key={r.id} run={r} busy={running} onUndo={() => undo(r.id)} />)}
      <Footer />
    </div>
  );
}
