import { useEffect, useMemo, useState } from 'react';
import { api, type DupGroup, type DupPlan, type DupResult } from '../api';
import type { StatusHook } from '../App';
import { Dot, Footer, JobProgress } from '../components';
import { libraryPath, middle, size, when } from '../labels';
import { Link, navigate, useLocation } from '../nav';

type Kind = 'all' | 'episode' | 'film';
const name = (p: string) => p.split('/').pop() ?? p;

function freed(g: DupGroup, keep: string) {
  return g.copies.filter((c) => c.path !== keep).reduce((n, c) => n + c.quality.size, 0);
}

function Group({ g, keep, plan, selected, onKeep, onSelect }: {
  g: DupGroup; keep: string; plan: DupPlan; selected: boolean; onKeep: (p: string) => void; onSelect: (on: boolean) => void;
}) {
  const quarantined = plan.ops.filter((o) => o.op === 'quarantine');
  const renamed = plan.ops.filter((o) => o.op === 'move');
  const watched = g.copies.some((c) => c.watched);
  return (
    <section className="panel" style={{ display: 'flex', flexDirection: 'column', gap: 10, borderColor: selected ? 'var(--accent)' : undefined }}>
      <div className="panel-head" style={{ marginBottom: 0 }}>
        <label className="choice" style={{ alignItems: 'center' }}>
          <input type="checkbox" checked={selected} onChange={(e) => onSelect(e.target.checked)} />
          <h2 style={{ fontSize: '1.1rem' }}>{g.label}</h2>
        </label>
        <span className="small muted">
          {g.show && <Link to={`/library?${new URLSearchParams({ folder: g.show })}`}>{g.show}</Link>}
          {g.note ? ` · ${g.note}` : ''}{watched ? ' · watched' : ''}
        </span>
      </div>
      <fieldset style={{ border: 0, padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
        <legend className="small muted" style={{ marginBottom: 4 }}>Which copy stays?</legend>
        {g.copies.map((c) => (
          <label key={c.path} className="choice" style={{ padding: '6px 8px', borderRadius: 'var(--radius-sm)', background: c.path === keep ? 'var(--surface-muted)' : undefined }}>
            <input type="radio" name={`keep-${g.id}`} checked={c.path === keep} onChange={() => onKeep(c.path)} />
            <span style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
              <span className="small"><strong>{c.label}</strong> · {size(c.quality.size)}{c.nfo ? ' · has NFO' : ''}{c.watched ? ' · watched' : ''}
                {c.path === g.keep && <span className="muted"> · muthur’s pick</span>}</span>
              <span className="mono small muted" title={libraryPath(c.path)} style={{ wordBreak: 'break-all' }}>{middle(libraryPath(c.path), 110)}</span>
            </span>
          </label>
        ))}
      </fieldset>
      <div className="small" style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        <span>Stays as <span className="mono" style={{ color: 'var(--accent-text)', wordBreak: 'break-all' }}>{libraryPath(plan.final)}</span></span>
        <span className="muted">
          To quarantine: {quarantined.length} {quarantined.length === 1 ? 'file' : 'files'} ({size(freed(g, keep))})
          {renamed.length > 0 ? ` · renamed: ${renamed.map((o) => name(o.src)).slice(0, 3).join(', ')}${renamed.length > 3 ? '…' : ''}` : ''}
        </span>
      </div>
    </section>
  );
}

export function DuplicatesPage({ status, refresh }: StatusHook) {
  const { search } = useLocation();
  const kind = (new URLSearchParams(search).get('show') ?? 'all') as Kind;
  const [data, setData] = useState<{ at: number | null; groups: DupGroup[] } | null>(null);
  const [keep, setKeep] = useState<Record<string, string>>({});
  const [plans, setPlans] = useState<Record<string, DupPlan>>({});
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [asking, setAsking] = useState(false);
  const [last, setLast] = useState<DupResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const running = Boolean(status?.job?.running);

  useEffect(() => {
    api.duplicates().then((d) => { setData(d); setSelected(new Set()); setKeep({}); setPlans({}); }).catch((e: Error) => setError(e.message));
    api.duplicatesLast().then((r) => setLast('items' in r ? (r as DupResult) : null)).catch(() => undefined);
  }, [running, status?.job?.finished]);

  const groups = useMemo(() => (data?.groups ?? []).filter((g) => kind === 'all' || g.kind === kind), [data, kind]);
  const keepOf = (g: DupGroup) => keep[g.id] ?? g.keep;
  const planOf = (g: DupGroup) => plans[g.id] ?? g.plan;
  const chosen = (data?.groups ?? []).filter((g) => selected.has(g.id));
  const files = chosen.reduce((n, g) => n + planOf(g).ops.filter((o) => o.op === 'quarantine').length, 0);
  const bytes = chosen.reduce((n, g) => n + freed(g, keepOf(g)), 0);

  const changeKeep = (g: DupGroup, path: string) => {
    setKeep((k) => ({ ...k, [g.id]: path }));
    api.duplicatePlan(g.id, path).then((p) => setPlans((x) => ({ ...x, [g.id]: p }))).catch((e: Error) => setError(e.message));
  };
  const select = (id: string, on: boolean) => setSelected((s) => { const n = new Set(s); if (on) n.add(id); else n.delete(id); return n; });
  const apply = () => {
    setAsking(false);
    setError(null);
    api.applyDuplicates(chosen.map((g) => ({ id: g.id, keep: keepOf(g) }))).then(refresh).catch((e: Error) => setError(e.message));
  };
  const check = () => { setError(null); api.scanDuplicates().then(refresh).catch((e: Error) => setError(e.message)); };

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">More than one copy</p>
          <h1>Duplicates</h1>
          <p className="lede">
            {data?.at ? `${data.groups.length} episodes and films have more than one copy · checked ${when(data.at)}` : 'Not checked yet.'}
          </p>
        </div>
        <div className="actions">
          {!asking && <button className="btn btn-secondary btn-sm" type="button" disabled={running} onClick={check}>{data?.at ? 'Check again' : 'Look for duplicates'}</button>}
          {!asking && (chosen.length > 0
            ? <button className="btn btn-primary" type="button" disabled={running} onClick={() => setAsking(true)}>Resolve {chosen.length} selected</button>
            : <button className="btn btn-primary" type="button" aria-disabled="true" title="Select groups first">Resolve selected</button>)}
        </div>
      </header>

      {asking && (
        <section className="panel" role="group" aria-labelledby="ask-h" style={{ display: 'flex', flexDirection: 'column', gap: 12, borderColor: 'var(--danger-text)' }}>
          <h2 id="ask-h" style={{ margin: 0, fontSize: '1.15rem', fontWeight: 650 }}>
            Move {files} {files === 1 ? 'file' : 'files'} ({size(bytes)}) to quarantine and keep one copy of {chosen.length} {chosen.length === 1 ? 'item' : 'items'}?
          </h2>
          <p className="hint">
            The copy that stays takes over the library name, NFO and artwork where that’s another copy’s. Kodi then scans those folders and the copy that
            stays gets the highest play count and resume point of all copies; their old entries are removed. muthur takes a fresh watched backup first.
            Everything can be put back from History.
          </p>
          <div className="actions" style={{ justifyContent: 'flex-end' }}>
            <button className="btn btn-secondary" type="button" autoFocus onClick={() => setAsking(false)}>Cancel</button>
            <button className="btn btn-danger" type="button" onClick={apply}>Move to quarantine</button>
          </div>
        </section>
      )}

      <JobProgress job={status?.job} />
      {error && <div className="banner banner-error" role="alert">{error}</div>}
      {last && !running && status?.job?.name === 'duplicates-apply' && (
        <div className={`banner ${last.stopped ? 'banner-warn' : 'banner-note'}`} role="status" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
          <span className="status"><Dot kind={last.stopped ? 'dot-warning' : 'dot-success'} />{last.applied} resolved{last.stopped ? `, ${last.stopped} stopped` : ''}. What moved is in History.</span>
          {last.items.filter((i) => !i.ok || (i.kodi && !i.kodi.ok)).map((i) => (
            <span key={i.id} className="small">{i.label}: {i.why ?? i.kodi?.why}</span>
          ))}
        </div>
      )}

      {data?.at && (
        <div className="inline" style={{ justifyContent: 'space-between' }}>
          <div className="seg filters" role="group" aria-label="Show">
            {([['all', 'All'], ['episode', 'Episodes'], ['film', 'Films']] as [Kind, string][]).map(([k, label]) => (
              <button key={k} type="button" aria-pressed={kind === k} onClick={() => navigate(k === 'all' ? '/duplicates' : `/duplicates?show=${k}`)}>
                {label} <span className="num muted">{(data.groups ?? []).filter((g) => k === 'all' || g.kind === k).length}</span>
              </button>
            ))}
          </div>
          {groups.length > 0 && (
            <label className="choice small">
              <input type="checkbox" checked={groups.every((g) => selected.has(g.id))}
                onChange={(e) => setSelected((s) => { const n = new Set(s); groups.forEach((g) => (e.target.checked ? n.add(g.id) : n.delete(g.id))); return n; })} />
              <span>Select all {groups.length} shown, with muthur’s picks</span>
            </label>
          )}
        </div>
      )}
      {data?.at && groups.length === 0 && (
        <section className="panel" style={{ textAlign: 'center', padding: '40px 16px' }}>
          <h2 style={{ margin: '0 0 6px', fontSize: '1.2rem' }}>No duplicates</h2>
          <p className="hint">Every episode and film has one copy.</p>
        </section>
      )}
      {groups.map((g) => (
        <Group key={g.id} g={g} keep={keepOf(g)} plan={planOf(g)} selected={selected.has(g.id)} onKeep={(p) => changeKeep(g, p)} onSelect={(on) => select(g.id, on)} />
      ))}
      <Footer />
    </div>
  );
}
