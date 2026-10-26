import { useEffect, useMemo, useState } from 'react';
import { api, type Inbox, type Item, type ItemStatus } from '../api';
import type { StatusHook } from '../App';
import { Dot, JobProgress, Loading } from '../components';
import { SIGNALS, STATUS, libraryPath, middle, size, splitId, when } from '../labels';
import { Link, navigate, useLocation } from '../nav';

const FILTERS: [ItemStatus | 'all', string][] = [['all', 'All'], ['ready', 'Ready'], ['review', 'Needs you'], ['suspicious', 'Suspicious'], ['packed', 'Packed'], ['waiting', 'Still downloading'], ['ignored', 'Ignored']];

function Detail({ item, onChanged }: { item: Item; onChanged: (note: string | null, error?: string) => void }) {
  const [busy, setBusy] = useState(false);
  const toQuarantine = () => {
    setBusy(true);
    api.quarantineDownload(item.id)
      .then(() => onChanged('Moved to quarantine. It can be put back from History, and is deleted for good only when you empty that day.'))
      .catch((e: Error) => onChanged(null, e.message))
      .finally(() => setBusy(false));
  };
  const s = STATUS[item.status] ?? { label: item.status, dot: '' };
  const placed = item.files.filter((f) => f.target);
  return (
    <aside className="panel narrow" aria-label="What would happen" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div>
        <p className="eyebrow">{s.label}</p>
        <h2 style={{ margin: '2px 0 0', fontSize: '1.3rem', fontWeight: 650, overflowWrap: 'anywhere' }}>{item.title ? `${item.title}${item.year ? ` (${item.year})` : ''}` : splitId(item.id).name}</h2>
        <p className="hint" style={{ marginTop: 4 }}>{item.reason}</p>
      </div>
      {placed.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {placed.map((f) => (
            <div key={f.source} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <span className="mono small muted" style={{ wordBreak: 'break-all' }}>{f.source}</span>
              <span className="mono small" style={{ wordBreak: 'break-all', color: 'var(--accent-text)' }}>→ {f.library}/{f.target}</span>
              {f.writes.length > 0 && <span className="small muted">Written next to it: {f.writes.join(', ')}</span>}
            </div>
          ))}
        </div>
      )}
      {item.notes.map((n) => <p key={n} className="hint">{n}</p>)}
      {item.status === 'review' && item.candidates.length > 0 && (
        <div>
          <h3 style={{ margin: '0 0 6px', fontSize: '1rem', fontWeight: 650 }}>What it could be</h3>
          <ul className="rows">
            {item.candidates.map((c) => (
              <li key={c.tmdbId} style={{ flexDirection: 'column', alignItems: 'flex-start' }}>
                <span><strong>{c.title}</strong>{c.year ? ` (${c.year})` : ''}{c.originalTitle && c.originalTitle !== c.title ? <span className="muted"> · {c.originalTitle}</span> : null}</span>
                <span className="small muted">
                  {Object.entries(c.signals).filter(([k]) => k !== 'popularity').map(([k, v]) => `${SIGNALS[k] ?? k} ${Math.round(v * 100)}%`).join(' · ')}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {item.status === 'review' && <Link to="/review" className="btn btn-secondary btn-sm" style={{ alignSelf: 'flex-start' }}>Choose in Review</Link>}
      {(item.status === 'suspicious' || item.status === 'packed') && (
        <button className="btn btn-secondary btn-sm" type="button" disabled={busy} aria-busy={busy} style={{ alignSelf: 'flex-start' }} onClick={toQuarantine}>Move to quarantine</button>
      )}
      <span className="small muted">{size(item.size)}</span>
    </aside>
  );
}

export function InboxPage({ status, refresh }: StatusHook) {
  const { search } = useLocation();
  const filter = (new URLSearchParams(search).get('show') ?? 'all') as ItemStatus | 'all';
  const [data, setData] = useState<Inbox | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const running = Boolean(status?.job?.running);

  useEffect(() => {
    api.inbox().then(setData).catch((e: Error) => setMessage(e.message));
  }, [status?.inbox.scannedAt, running]);

  const items = useMemo(() => (data?.items ?? []).filter((i) => filter === 'all' || i.status === filter), [data, filter]);
  const current = items.find((i) => i.id === selected) ?? items[0] ?? null;
  const count = (k: ItemStatus | 'all') => (k === 'all' ? data?.items.length : data?.items.filter((i) => i.status === k).length) ?? 0;

  const [starting, setStarting] = useState<string | null>(null);
  const begin = (key: string, request: () => Promise<unknown>) => {
    setStarting(key);
    setMessage(null);
    request().then(refresh).catch((e: Error) => setMessage(e.message)).finally(() => setStarting(null));
  };
  const scan = () => begin('scan', api.scan);

  const ready = (data?.items ?? []).filter((i) => i.status === 'ready');
  const [asking, setAsking] = useState(false);
  const toTv = ready.filter((i) => i.kind === 'tv').reduce((n, i) => n + i.files.filter((f) => f.target).length, 0);
  const toFilm = ready.filter((i) => i.kind === 'movie').length;
  const newShows = new Set(ready.filter((i) => i.kind === 'tv' && !i.known).map((i) => i.files[0]?.target?.split('/')[0])).size;
  const apply = () => {
    setAsking(false);
    begin('apply', () => api.apply());
  };

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">Finished downloads</p>
          <h1>Inbox</h1>
          <p className="lede">
            {status && <><span className="mono small" style={{ overflowWrap: 'anywhere' }}>{libraryPath(status.paths.downloads.path)}</span> · </>}checked {when(data?.scannedAt ?? null)}
          </p>
        </div>
        <div className="actions">
          {asking ? null : ready.length > 0 ? (
            <>
              <button className="btn btn-secondary btn-sm" type="button" disabled={!status?.tmdb.configured} aria-busy={starting === 'scan'} onClick={scan}>Look again</button>
              <button className="btn btn-primary" type="button" aria-busy={starting === 'apply'} onClick={() => setAsking(true)}>
                Apply {ready.length} ready {ready.length === 1 ? 'item' : 'items'}
              </button>
            </>
          ) : (
            <button className="btn btn-primary" type="button" disabled={!status?.tmdb.configured} aria-busy={starting === 'scan'} onClick={scan}>Look for new downloads</button>
          )}
        </div>
      </header>

      {asking && (
        <section className="panel" role="group" aria-labelledby="ask-h" style={{ display: 'flex', flexDirection: 'column', gap: 12, borderColor: 'var(--mark)' }}>
          <h2 id="ask-h" style={{ margin: 0, fontSize: '1.15rem', fontWeight: 650 }}>
            Move {ready.length} {ready.length === 1 ? 'download' : 'downloads'} into your library?
          </h2>
          <ul className="rows">
            {toTv > 0 && <li><span>Episodes into TV</span><span className="num">{toTv}{newShows > 0 ? ` · ${newShows} new show folder${newShows === 1 ? '' : 's'}` : ''}</span></li>}
            {toFilm > 0 && <li><span>Films into Film</span><span className="num">{toFilm}</span></li>}
            <li><span>Written next to them</span><span>NFO files and artwork, only where none exist</span></li>
            <li><span>What’s left of each download</span><span>to quarantine, if it holds no video</span></li>
          </ul>
          <p className="hint">Nothing is overwritten; History can put it back.</p>
          <div className="actions" style={{ justifyContent: 'flex-end' }}>
            <button className="btn btn-secondary" type="button" autoFocus onClick={() => setAsking(false)}>Cancel</button>
            <button className="btn btn-primary" type="button" onClick={apply}>Move them</button>
          </div>
        </section>
      )}

      {message && <div className="banner banner-error" role="alert">{message}</div>}
      {note && <div className="banner banner-note" role="status">{note}</div>}
      <JobProgress job={status?.job} queue={status?.queue} />
      {!data && !message && <Loading label="Loading the downloads" />}
      {status?.job && !status.job.running && status.job.name === 'apply' && !status.job.error && (
        <div className="banner banner-note" role="status">
          <span className="status"><Dot kind="dot-success" />Done. What moved, and the way to put it back, is in History.</span>
          <Link to="/history">Open History</Link>
        </div>
      )}

      <div className="seg filters" role="group" aria-label="Show">
        {FILTERS.map(([k, label]) => (
          <button key={k} type="button" aria-pressed={filter === k} onClick={() => navigate(k === 'all' ? '/inbox' : `/inbox?show=${k}`)}>
            {label} <span className="num muted">{count(k)}</span>
          </button>
        ))}
      </div>

      {data && data.items.length === 0 && !running ? (
        <section className="panel" style={{ textAlign: 'center', padding: '40px 16px' }}>
          <h2 style={{ margin: '0 0 6px', fontSize: '1.2rem' }}>{data.scannedAt ? 'Nothing waiting' : 'Not checked yet'}</h2>
          <p className="hint">{data.scannedAt ? 'Nothing finished yet.' : 'Check the downloads to see what’s there.'}</p>
        </section>
      ) : (
        <div className="split">
          <section className="panel wide" aria-label="Downloads" style={{ padding: '10px 14px' }}>
            <div className="list-head"><span>Download</span><span>Would become</span><span>Status</span></div>
            {items.map((i) => {
              const s = STATUS[i.status] ?? { label: i.status, dot: '' };
              return (
                <button key={i.id} type="button" className="list-row" aria-pressed={current?.id === i.id} onClick={() => setSelected(i.id)}>
                  <span style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }} title={i.id}>
                    <span className="mono small">{middle(splitId(i.id).name, 46)}</span>
                    {splitId(i.id).folder && <span className="small muted">in {splitId(i.id).folder}</span>}
                  </span>
                  <span style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
                    {i.title && <span className="ellipsis" style={{ fontWeight: 600 }}>{i.title}{i.year ? ` (${i.year})` : ''}</span>}
                    <span className={i.title ? 'small muted ellipsis' : 'small ellipsis'}>{i.reason}</span>
                  </span>
                  <span className="status small"><Dot kind={s.dot} />{s.label}</span>
                </button>
              );
            })}
            {items.length === 0 && <p className="hint" style={{ padding: 12 }}>Nothing in this group.</p>}
          </section>
          {current && <Detail item={current} onChanged={(text, error) => {
            setNote(text);
            setMessage(error ?? null);
            if (text) {
              api.inbox().then(setData).catch(() => undefined);
              refresh();  // the counters, tabs and Dashboard banner come from the status, not the list
            }
          }} />}
        </div>
      )}
    </div>
  );
}
