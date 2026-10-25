import { useCallback, useEffect, useState } from 'react';
import { api, type Status } from './api';
import { Icon } from './icons';
import { Link, useLocation } from './nav';
import { useTheme, type ThemeChoice } from './theme';
import { Dashboard } from './pages/Dashboard';
import { InboxPage } from './pages/Inbox';
import { SettingsPage } from './pages/Settings';

// Only pages that exist are in the navigation (DESIGN.md §1.5).
const SECTIONS = [
  { to: '/', label: 'Dashboard', icon: 'dashboard' },
  { to: '/inbox', label: 'Inbox', icon: 'inbox' },
  { to: '/settings', label: 'Settings', icon: 'settings' },
] as const;

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

function RailFoot({ status }: { status: Status | null }) {
  const k = status?.kodi;
  return (
    <div className="rail-foot">
      {k === undefined ? null : k === null ? (
        <span className="status"><span className="dot" />Kodi not set up</span>
      ) : k.connected ? (
        <span className="status"><span className="dot dot-success" />Shield · Kodi {k.version}</span>
      ) : (
        <span className="status"><span className="dot dot-danger" />Kodi unreachable</span>
      )}
      {status && !status.applying && <span className="status"><span className="dot dot-warning" />Plans only, moves nothing</span>}
      <ThemeSwitch />
    </div>
  );
}

export function App() {
  const { path } = useLocation();
  const hook = useStatus();
  const counts = hook.status?.inbox.counts ?? {};
  const waiting = (counts.ready ?? 0) + (counts.review ?? 0);
  const current = SECTIONS.find((s) => s.to === path) ?? SECTIONS[0];

  useEffect(() => {
    document.title = current.to === '/' ? 'muthur' : `${current.label} · muthur`;
  }, [current]);

  return (
    <div className="shell">
      <nav className="rail" aria-label="Main">
        <Link to="/" className="brand" aria-label="muthur, dashboard">
          <span className="brand-mark" aria-hidden="true" />
          <span><span className="brand-name">MU/TH/UR</span><br /><span className="brand-sub">muthur · nostromo</span></span>
        </Link>
        <div className="rail-nav">
          {SECTIONS.map((s) => (
            <Link key={s.to} to={s.to} className="rail-link" aria-current={current.to === s.to ? 'page' : undefined}>
              <Icon name={s.icon} />{s.label}
              {s.to === '/inbox' && waiting > 0 && <span className="counter">{waiting}</span>}
            </Link>
          ))}
        </div>
        <RailFoot status={hook.status} />
      </nav>

      <header className="topbar">
        <Link to="/" className="brand" aria-label="muthur, dashboard">
          <span className="brand-mark" aria-hidden="true" /><span className="brand-name">MU/TH/UR</span>
        </Link>
        <ThemeSwitch />
      </header>

      <main className="main" id="main">
        {current.to === '/' && <Dashboard {...hook} />}
        {current.to === '/inbox' && <InboxPage {...hook} />}
        {current.to === '/settings' && <SettingsPage {...hook} />}
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
