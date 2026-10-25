import { useEffect, useState } from 'react';
import { api } from '../api';
import { libraryPath, size } from '../labels';

type Day = { day: string; files: number; size: number };

// The quarantine, per day. Emptying deletes for good, so it only happens on the reader's confirmation (DESIGN.md §7.3).
export function QuarantinePanel({ busy }: { busy: boolean }) {
  const [days, setDays] = useState<Day[] | null>(null);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [asking, setAsking] = useState(false);
  const [message, setMessage] = useState<{ kind: 'error' | 'note'; text: string } | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [notes, setNotes] = useState<{ from: string; why: string }[]>([]);
  const show = (day: string) => {
    if (open === day) { setOpen(null); return; }
    api.quarantineDay(day).then((r) => { setNotes(r.notes); setOpen(day); }).catch((e: Error) => setMessage({ kind: 'error', text: e.message }));
  };

  const load = () => api.quarantine().then((q) => { setDays(q.days); setChosen(new Set()); }).catch((e: Error) => setMessage({ kind: 'error', text: e.message }));
  useEffect(() => { load(); }, [busy]); // eslint-disable-line react-hooks/exhaustive-deps

  const picked = (days ?? []).filter((d) => chosen.has(d.day));
  const files = picked.reduce((n, d) => n + d.files, 0);
  const bytes = picked.reduce((n, d) => n + d.size, 0);
  const empty = () => {
    setAsking(false);
    api.emptyQuarantine(picked.map((d) => d.day))
      .then((r) => { setMessage({ kind: 'note', text: `Deleted ${size(r.freed)} for good.` }); load(); })
      .catch((e: Error) => setMessage({ kind: 'error', text: e.message }));
  };

  return (
    <section className="panel" aria-labelledby="q-h" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div className="panel-head" style={{ marginBottom: 0 }}>
        <h2 id="q-h">Quarantine</h2>
        <span className="small muted">{days ? `${(days ?? []).reduce((n, d) => n + d.files, 0)} files · ${size((days ?? []).reduce((n, d) => n + d.size, 0) || 1)}` : ''}</span>
      </div>
      {days && days.length === 0 && <p className="hint">Empty.</p>}
      {days && days.length > 0 && (
        <ul className="rows">
          {days.map((d) => (
            <li key={d.day} style={{ flexDirection: 'column', gap: 4 }}>
              <span style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
                <label className="choice">
                  <input type="checkbox" checked={chosen.has(d.day)} onChange={(e) => setChosen((s) => { const n = new Set(s); if (e.target.checked) n.add(d.day); else n.delete(d.day); return n; })} />
                  <span>{new Date(d.day).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}</span>
                </label>
                <span className="small num">{d.files} files · {size(d.size || 1)} · <button type="button" className="btn-link small" onClick={() => show(d.day)}>{open === d.day ? 'Hide' : 'What and why'}</button></span>
              </span>
              {open === d.day && (notes.length ? (
                <ul className="rows" style={{ paddingLeft: 26 }}>
                  {notes.map((n, i) => (
                    <li key={i} style={{ flexDirection: 'column', gap: 2 }}>
                      <span className="mono small" style={{ wordBreak: 'break-all' }}>{libraryPath(n.from)}</span>
                      <span className="small muted">{n.why}</span>
                    </li>
                  ))}
                </ul>
              ) : <p className="hint" style={{ paddingLeft: 26 }}>No notes for this day; it was filled before muthur kept them.</p>)}
            </li>
          ))}
        </ul>
      )}
      {asking && (
        <div className="banner banner-error" role="group" aria-label="Empty quarantine" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
          <strong>Delete {files} {files === 1 ? 'file' : 'files'} ({size(bytes || 1)}) for good?</strong>
          <span>This can’t be undone, and History can no longer put these files back.</span>
          <div className="actions" style={{ justifyContent: 'flex-end' }}>
            <button className="btn btn-secondary btn-sm" type="button" autoFocus onClick={() => setAsking(false)}>Cancel</button>
            <button className="btn btn-danger btn-sm" type="button" onClick={empty}>Delete for good</button>
          </div>
        </div>
      )}
      {message && <div className={`banner banner-${message.kind}`} role="status">{message.text}</div>}
      {!asking && picked.length > 0 && (
        <div className="actions"><button className="btn btn-danger-outline btn-sm" type="button" disabled={busy} onClick={() => setAsking(true)}>Empty {picked.length} {picked.length === 1 ? 'day' : 'days'}…</button></div>
      )}
    </section>
  );
}
