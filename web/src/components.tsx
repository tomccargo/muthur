// Small pieces shared by the pages.
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
        <div className="track" aria-hidden="true"><span className="fill" style={{ width: `${pct}%` }} /></div>
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
