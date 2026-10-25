// Small pieces shared by the pages.
import type { ReactNode } from 'react';
import type { Job } from './api';
import { JOBS } from './labels';

export function Dot({ kind = '' }: { kind?: string }) {
  return <span className={`dot ${kind}`} aria-hidden="true" />;
}

export function JobProgress({ job }: { job: Job | null | undefined }) {
  if (!job) return null;
  const label = JOBS[job.name] ?? job.name;
  if (job.running) {
    const pct = job.total ? Math.round((job.done / job.total) * 100) : 0;
    return (
      <div className="panel" role="status" aria-live="polite" style={{ padding: '14px 18px', display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, fontSize: 14 }}>
          <span>{label}…</span>
          <span className="muted num">{job.total ? `${job.done} of ${job.total}` : 'starting'}</span>
        </div>
        <div className="bulb-strip" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label={label}>
          {Array.from({ length: 24 }, (_, i) => <i key={i} className={i < Math.round((pct / 100) * 24) ? 'on' : ''} />)}
        </div>
      </div>
    );
  }
  if (job.error) {
    return <div className="banner banner-error" role="alert">{label} stopped with a problem: {job.error}</div>;
  }
  return null;
}

// Mother's room (DESIGN.md §11): where muthur speaks. One light per item (lit = present), working only while a job runs.
export function MotherConsole({ lights, lit, busy = false, label = 'muthur', children }: {
  lights: number; lit: number; busy?: boolean; label?: string; children: ReactNode;
}) {
  return (
    <section className="mother" aria-label={label}>
      {[0, 1].map((side) => (
        <div key={side} className={`mother-lights${busy ? ' busy' : ''}${side ? ' right' : ''}`} aria-hidden="true">
          {Array.from({ length: lights / 2 }, (_, i) => <i key={i} className={side * (lights / 2) + i < lit ? 'on' : ''} />)}
        </div>
      ))}
      <div className="crt">{children}</div>
    </section>
  );
}

export function Footer() {
  return (
    <p className="foot">
      Data and images from TMDB. This product uses the TMDB API but is not endorsed or certified by TMDB.
    </p>
  );
}
