// Small pieces shared by the pages.
import { useEffect, useRef, useState, type ReactNode } from 'react';
import type { Job } from './api';
import { JOBS } from './labels';

export function Dot({ kind = '' }: { kind?: string }) {
  return <span className={`dot ${kind}`} aria-hidden="true" />;
}

export function JobProgress({ job, queue }: { job: Job | null | undefined; queue?: Job[] }) {
  if (!job) return null;
  const next = queue?.length ? <span className="small muted">Next: {queue.map((j) => JOBS[j.name] ?? j.name).join(', then ')}</span> : null;
  const label = JOBS[job.name] ?? job.name;
  if (job.running) {
    const pct = job.total ? Math.round((job.done / job.total) * 100) : 0;
    return (
      <div className="panel" role="status" aria-live="polite" style={{ padding: '14px 18px', display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, fontSize: 14 }}>
          <span>{job.step ?? label}…</span>
          <span className="muted num">{job.total ? `${job.done} of ${job.total}` : 'starting'}</span>
        </div>
        {/* Before a job has counted its work, the bar moves without claiming a share (DESIGN.md §6). */}
        <div className="track" aria-hidden="true">
          {job.total ? <span className="fill" style={{ width: `${pct}%` }} /> : <span className="fill indeterminate" />}
        </div>
        {next}
      </div>
    );
  }
  if (job.error) {
    return <div className="banner banner-error" role="alert">{label} stopped with a problem: {job.error}</div>;
  }
  return null;
}

export function Footer() {
  return (
    <p className="foot">
      Data and images from TMDB. This product uses the TMDB API but is not endorsed or certified by TMDB.
    </p>
  );
}

// Set-up instructions: read once, so they stay folded until asked for (DESIGN.md §1.11).
export function HowTo({ children }: { children: ReactNode }) {
  return <details className="howto"><summary className="small">How to set this up</summary><p className="hint">{children}</p></details>;
}

// ---- Waiting, the same everywhere (DESIGN.md §7.6) ---------------------------------------------------

// A small ring inside the button that was pressed, while its request runs.
export function Spinner() {
  return <span className="spinner" aria-hidden="true" />;
}

type Result = { kind: 'note' | 'error'; text: string; key: string };

// One action at a time per section: the button pressed shows the spinner (busy = its key), the others wait,
// and the result or error stays in the section until the next action. busy always clears, also on errors.
export function useAction() {
  const [busy, setBusy] = useState<string | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const running = useRef(false);
  const run = <T,>(key: string, request: () => Promise<T>, done?: (r: T) => string | void) => {
    if (running.current) return;  // a second click while the first runs does nothing
    running.current = true;
    setBusy(key);
    setResult(null);
    request()
      .then((r) => { const text = done?.(r); if (text) setResult({ kind: 'note', text, key }); })
      .catch((e: Error) => setResult({ kind: 'error', text: e.message, key }))
      .finally(() => { running.current = false; setBusy(null); });
  };
  return { busy, result, run, clear: () => setResult(null) };
}

// The result of a section's action, where the action was taken.
export function ActionResult({ result }: { result: Result | null }) {
  if (!result) return null;
  return <div className={`banner banner-${result.kind}`} role={result.kind === 'error' ? 'alert' : 'status'}>{result.text}</div>;
}

// Seconds since a wait began, shown once it takes longer than 3 s ('Waking the Shield… 12 s').
export function useElapsed(active: boolean) {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    if (!active) { setSeconds(0); return; }
    const t0 = Date.now();
    const id = window.setInterval(() => setSeconds(Math.round((Date.now() - t0) / 1000)), 1000);
    return () => window.clearInterval(id);
  }, [active]);
  return active && seconds >= 3 ? ` ${seconds} s` : '';
}

// Where a page's data will be, while it loads.
export function Loading({ rows = 3, label }: { rows?: number; label: string }) {
  return (
    <section className="panel" aria-busy="true" aria-label={label} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {Array.from({ length: rows }, (_, i) => <span key={i} className="skeleton" style={{ width: `${90 - i * 18}%` }} />)}
    </section>
  );
}

// A page whose data didn't load: the reason and a way to try again (DESIGN.md §1.5).
export function LoadFailed({ error, retry }: { error: string; retry: () => void }) {
  return (
    <div className="banner banner-error" role="alert">
      <span>Couldn’t load this: {error}</span>
      <button type="button" className="btn-link" onClick={retry}>Try again</button>
    </div>
  );
}

// The running job in the rail, on every page: its step and count.
export function JobLine({ job }: { job: Job | null | undefined }) {
  if (!job?.running) return null;
  const pct = job.total ? Math.round((job.done / job.total) * 100) : 0;
  return (
    <span className="rail-job" role="status">
      <span className="status small"><Spinner />{job.step ?? JOBS[job.name] ?? job.name}</span>
      <span className="track" aria-hidden="true">
        {job.total ? <span className="fill" style={{ width: `${pct}%` }} /> : <span className="fill indeterminate" />}
      </span>
    </span>
  );
}
