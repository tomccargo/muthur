// Small pieces shared by the pages.
import { useEffect, useRef, useState, type InputHTMLAttributes, type ReactNode } from 'react';
import type { Job } from './api';
import { Icon } from './icons';
import { JOBS } from './labels';

// A text field with a cross at its end that empties it, shown while there is text (27 Oct). Escape empties it too.
type ClearFieldProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'value' | 'onChange'> & { value: string; onChange: (v: string) => void };
export function ClearField({ value, onChange, className = 'field', onKeyDown, ...rest }: ClearFieldProps) {
  const ref = useRef<HTMLInputElement>(null);
  const clear = () => { onChange(''); ref.current?.focus(); };
  return (
    <span className="clear-field">
      <input ref={ref} className={className} value={value} onChange={(e) => onChange(e.target.value)} {...rest}
        onKeyDown={(e) => { if (e.key === 'Escape' && value) { e.preventDefault(); clear(); } onKeyDown?.(e); }} />
      {value && <button type="button" className="clear-btn" aria-label="Clear" title="Clear" onClick={clear}><Icon name="x" size={16} /></button>}
    </span>
  );
}

export function Dot({ kind = '' }: { kind?: string }) {
  return <span className={`dot ${kind}`} aria-hidden="true" />;
}

// A job that stopped with a problem, said on the page where it matters. A running job never takes room on the
// page: it is the bar along the top and the line in the rail (DESIGN.md §7.6).
export function JobError({ job }: { job: Job | null | undefined }) {
  if (!job || job.running || !job.error) return null;
  return <div className="banner banner-error" role="alert">{JOBS[job.name] ?? job.name} stopped with a problem: {job.error}</div>;
}

// True once `active` has lasted `delay` ms, and then for at least `least` ms: a short job never flashes.
function useLingering(active: boolean, delay = 400, least = 600) {
  const [shown, setShown] = useState(false);
  const since = useRef(0);
  useEffect(() => {
    if (active && !shown) {
      const t = window.setTimeout(() => { since.current = Date.now(); setShown(true); }, delay);
      return () => window.clearTimeout(t);
    }
    if (!active && shown) {
      const t = window.setTimeout(() => setShown(false), Math.max(0, least - (Date.now() - since.current)));
      return () => window.clearTimeout(t);
    }
    return undefined;
  }, [active, shown, delay, least]);
  return shown;
}

// The running job as a thin bar pinned to the top of the window, over the page: it moves nothing when it comes or goes.
export function JobBar({ job }: { job: Job | null | undefined }) {
  const shown = useLingering(Boolean(job?.running));
  const pct = job?.running && job.total ? Math.round((job.done / job.total) * 100) : job?.running ? 0 : 100;
  return (
    <div className={`job-bar${shown ? ' on' : ''}`} aria-hidden="true">
      {/* Before a job has counted its work, the bar moves without claiming a share (DESIGN.md §6). */}
      {job?.running && !job.total ? <span className="fill indeterminate" /> : <span className="fill" style={{ width: `${pct}%` }} />}
    </div>
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
export function JobLine({ job, queue }: { job: Job | null | undefined; queue?: Job[] }) {
  if (!job?.running) return null;
  const pct = job.total ? Math.round((job.done / job.total) * 100) : 0;
  return (
    <span className="rail-job" role="status" aria-live="polite">
      <span className="status small"><Spinner />{job.step ?? JOBS[job.name] ?? job.name}</span>
      <span className="track" aria-hidden="true">
        {job.total ? <span className="fill" style={{ width: `${pct}%` }} /> : <span className="fill indeterminate" />}
      </span>
      {job.total > 0 && <span className="small muted num">{job.done.toLocaleString('en-GB')} of {job.total.toLocaleString('en-GB')}</span>}
      {queue?.length ? <span className="small muted">Next: {queue.map((j) => JOBS[j.name] ?? j.name).join(', then ')}</span> : null}
    </span>
  );
}
