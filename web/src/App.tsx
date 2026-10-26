import { useCallback, useEffect, useState } from 'react';
import { AUTH_EVENT, api, type AuthMode, type Status } from './api';
import { Icon } from './icons';
import { Backdrop } from './Backdrop';
import { JobBar, JobLine, Spinner } from './components';
import { when } from './labels';
import { Link, useLocation } from './nav';
import { useTheme, type ThemeChoice } from './theme';
import { Dashboard } from './pages/Dashboard';
import { InboxPage } from './pages/Inbox';
import { SettingsPage } from './pages/Settings';
import { HistoryPage } from './pages/History';
import { ReviewPage } from './pages/Review';
import { LibraryPage } from './pages/Library';
import { DuplicatesPage } from './pages/Duplicates';
import { HealthPage } from './pages/Health';
import { SignIn } from './pages/SignIn';

// Five sections, one per job (DESIGN.md §1.4): the downloads, the library, what muthur did, and how it works.
// Downloads and Library hold their pages as tabs. Only pages that exist are in the navigation (§1.5).
const SECTIONS = [
  { to: '/', label: 'Dashboard', icon: 'dashboard', paths: ['/'] },
  { to: '/inbox', label: 'Downloads', icon: 'inbox', paths: ['/inbox', '/review'] },
  { to: '/library', label: 'Library', icon: 'library', paths: ['/library', '/duplicates'] },
  // Its own place, not a tab under Library: what needs fixing is found from anywhere (DESIGN.md §1.4).
  { to: '/health', label: 'Health', icon: 'health', paths: ['/health'] },
  { to: '/history', label: 'History', icon: 'history', paths: ['/history'] },
  { to: '/settings', label: 'Settings', icon: 'settings', paths: ['/settings'] },
] as const;
const TABS: Record<string, { to: string; label: string }[]> = {
  '/inbox': [{ to: '/inbox', label: 'Inbox' }, { to: '/review', label: 'Review' }],
  '/library': [{ to: '/library', label: 'Shows and films' }, { to: '/duplicates', label: 'Duplicates' }],
};
const TITLES: Record<string, string> = {
  '/inbox': 'Inbox', '/review': 'Review', '/library': 'Library', '/duplicates': 'Duplicates', '/health': 'Health', '/history': 'History', '/settings': 'Settings',
};

export type StatusHook = { status: Status | null; error: string | null; refresh: () => void };

function useStatus(): StatusHook {
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refresh = useCallback(() => {
    api.status().then((s) => { setStatus(s); setError(null); }).catch((e: Error) => setError(e.message));
  }, []);
  useEffect(() => {
    refresh();
    // Faster while a job runs, so its progress is visible; slow otherwise.
    const id = window.setInterval(refresh, status?.job?.running ? 1000 : 15000);
    return () => window.clearInterval(id);
  }, [refresh, status?.job?.running]);
  return { status, error, refresh };
}

function ThemeSwitch() {
  const [theme, setTheme] = useTheme();
  const options: [ThemeChoice, string, string][] = [['system', 'monitor', 'Follow the system'], ['dark', 'moon', 'Dark'], ['light', 'sun', 'Light']];
  return (
    <div className="seg" role="group" aria-label="Theme">
      {options.map(([value, icon, label]) => (
        <button key={value} type="button" aria-pressed={theme === value} aria-label={label} title={label} onClick={() => setTheme(value)}>
          <Icon name={icon} size={15} />
        </button>
      ))}
    </div>
  );
}

function RailFoot({ status, onChange }: { status: Status | null; onChange: () => void }) {
  const k = status?.kodi;
  const [waking, setWaking] = useState(false);
  return (
    <div className="rail-foot">
      <JobLine job={status?.job} queue={status?.queue} />
      {k === undefined ? null : k === null ? (
        <span className="status"><span className="dot" />Kodi not set up</span>
      ) : k.connected ? (
        <span className="status"><span className="dot dot-success" />{status?.names.device} · Kodi {k.version}</span>
      ) : (
        <span className="status"><span className="dot dot-danger" />Kodi unreachable
          {k.canWake && (waking ? <span className="small"><Spinner /> Waking…</span>
            : <button type="button" className="btn-link small" onClick={() => { setWaking(true); api.wakeShield().catch(() => undefined).finally(() => { setWaking(false); onChange(); }); }}>Wake</button>)}
        </span>
      )}
      {status && !status.applying && <span className="status"><span className="dot dot-warning" />Dry run on</span>}
      {status?.watched.paused ? <span className="status"><span className="dot dot-danger" />Watched backup paused</span>
        : status?.watched.last ? <span className="status"><span className="dot dot-success" />Backed up {when(status.watched.last.at)}</span> : null}
      <ThemeSwitch />
    </div>
  );
}

// Signed in first (ARCHITECTURE.md §14); the app itself only once the server says this browser may.
export function App() {
  const [auth, setAuth] = useState<'checking' | 'ok' | AuthMode>('checking');
  useEffect(() => {
    api.auth().then((a) => setAuth(a.signedIn ? 'ok' : a.set ? 'login' : 'setup')).catch(() => setAuth('ok'));
    const onAuth = (e: Event) => setAuth((e as CustomEvent<AuthMode>).detail);
    window.addEventListener(AUTH_EVENT, onAuth);
    return () => window.removeEventListener(AUTH_EVENT, onAuth);
  }, []);
  if (auth === 'checking') return null;
  if (auth !== 'ok') return <SignIn mode={auth} onDone={() => setAuth('ok')} />;
  return <Shell />;
}

// On a phone the rail's status isn't there: one dot in the top bar says whether Kodi and the backup are fine.
function StatusDot({ status }: { status: Status | null }) {
  const k = status?.kodi;
  const text = !k ? 'Kodi not set up' : !k.connected ? 'Kodi unreachable' : status?.watched.paused ? 'Watched backup paused'
    : `${status?.names.device} · Kodi ${k.version}`;
  const kind = !k ? '' : k.connected && !status?.watched.paused ? 'dot-success' : 'dot-danger';
  if (status?.job?.running) {
    const what = status.job.step ?? status.job.name;
    return <Link to="/" className="topbar-status" aria-label={`Working: ${what}`} title={`Working: ${what}`}><Spinner /></Link>;
  }
  return <Link to="/settings" className="topbar-status" aria-label={text} title={text}><span className={`dot ${kind}`} /></Link>;
}

function Shell() {
  const { path } = useLocation();
  const hook = useStatus();
  const counts = hook.status?.inbox.counts ?? {};
  const counter: Record<string, number> = { '/inbox': counts.ready ?? 0, '/review': counts.review ?? 0, '/duplicates': hook.status?.duplicates ?? 0, '/health': hook.status?.fixes ?? 0 };
  const page = path in TITLES ? path : '/';
  const current = SECTIONS.find((s) => (s.paths as readonly string[]).includes(page)) ?? SECTIONS[0];
  const total = (s: (typeof SECTIONS)[number]) => s.paths.reduce((n, p) => n + (counter[p] ?? 0), 0);

  useEffect(() => {
    document.title = page === '/' ? 'muthur' : `${TITLES[page]} · muthur`;
  }, [page]);

  return (
    <div className="shell">
      <Backdrop />
      <JobBar job={hook.status?.job} />
      <a className="skip-link" href="#main">Skip to the page</a>
      <nav className="rail" aria-label="Main">
        <Link to="/" className="brand" aria-label="muthur, dashboard">
          <span className="brand-mark" aria-hidden="true" />
          <span><span className="brand-name">MU/TH/UR</span><br />
            <span className="brand-sub">{hook.status?.names.nas ? `muthur · ${hook.status.names.nas.toLowerCase()}` : 'muthur'}</span></span>
        </Link>
        <div className="rail-nav">
          {SECTIONS.map((s) => (
            <Link key={s.to} to={s.to} className="rail-link" aria-current={current.to === s.to ? 'page' : undefined}>
              <Icon name={s.icon} />{s.label}
              {total(s) > 0 && <span className="counter">{total(s)}</span>}
            </Link>
          ))}
        </div>
        <RailFoot status={hook.status} onChange={hook.refresh} />
      </nav>

      <header className="topbar">
        <Link to="/" className="brand" aria-label="muthur, dashboard">
          <span className="brand-mark" aria-hidden="true" /><span className="brand-name">MU/TH/UR</span>
        </Link>
        <StatusDot status={hook.status} />
        <ThemeSwitch />
      </header>

      <main className="main" id="main" tabIndex={-1}>
        {TABS[current.to] && (
          <nav className="section-tabs" aria-label={current.label}>
            {TABS[current.to].map((t) => (
              <Link key={t.to} to={t.to} className="section-tab" aria-current={page === t.to ? 'page' : undefined}>
                {t.label}{(counter[t.to] ?? 0) > 0 && <span className="counter">{counter[t.to]}</span>}
              </Link>
            ))}
          </nav>
        )}
        {page === '/' && <Dashboard {...hook} />}
        {page === '/inbox' && <InboxPage {...hook} />}
        {page === '/review' && <ReviewPage {...hook} />}
        {page === '/library' && <LibraryPage {...hook} />}
        {page === '/duplicates' && <DuplicatesPage {...hook} />}
        {page === '/health' && <HealthPage {...hook} />}
        {page === '/history' && <HistoryPage {...hook} />}
        {page === '/settings' && <SettingsPage {...hook} />}
      </main>

      <nav className="tabbar" aria-label="Main">
        {SECTIONS.map((s) => (
          <Link key={s.to} to={s.to} className="tab" aria-current={current.to === s.to ? 'page' : undefined}>
            <Icon name={s.icon} size={20} />{s.label}
          </Link>
        ))}
      </nav>
    </div>
  );
}
