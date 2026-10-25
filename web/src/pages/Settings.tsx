import { useEffect, useState } from 'react';
import { api, type KodiState, type Settings } from '../api';
import type { StatusHook } from '../App';
import { Dot, Footer } from '../components';
import { PasswordSettings } from './PasswordSettings';
import { ShieldSettings, type ShieldDraft } from './ShieldSettings';
import { ALL_LANGUAGES, METADATA_LANGUAGES, language, libraryPath, metadataLanguage } from '../labels';

type Draft = {
  host: string; port: string; tcpPort: string; user: string; password: string; token: string; tmdbLanguage: string; keepOriginal: string[];
  dsUrl: string; dsUser: string; dsPassword: string; dryRun: boolean; preferHdr: boolean;
} & ShieldDraft;
type DsState = { connected: true; tasks: number } | { connected: false; problem: string };

function toDraft(s: Settings): Draft {
  return {
    host: s.kodi.host, port: String(s.kodi.port), tcpPort: String(s.kodi.tcpPort), user: s.kodi.user, password: '', token: '',
    tmdbLanguage: s.tmdb.language, keepOriginal: s.titles.keepOriginal,
    dsUrl: s.downloadStation.url, dsUser: s.downloadStation.user, dsPassword: '', dryRun: s.dryRun, preferHdr: s.quality.preferHdr,
    shieldOn: s.shield.enabled, shieldPort: String(s.shield.port), shieldApp: s.shield.app,
  };
}

export function SettingsPage({ refresh }: StatusHook) {
  const [saved, setSaved] = useState<Settings | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [dirty, setDirty] = useState(false);
  const [message, setMessage] = useState<{ kind: 'error' | 'note'; text: string } | null>(null);
  const [kodi, setKodi] = useState<KodiState | null>(null);
  const [testing, setTesting] = useState(false);
  const [ds, setDs] = useState<DsState | null>(null);

  useEffect(() => {
    api.settings().then((s) => { setSaved(s); setDraft(toDraft(s)); }).catch((e: Error) => setMessage({ kind: 'error', text: e.message }));
  }, []);

  if (!draft || !saved) {
    return <div className="page">{message && <div className="banner banner-error" role="alert">{message.text}</div>}</div>;
  }

  const edit = (patch: Partial<Draft>) => { setDraft({ ...draft, ...patch }); setDirty(true); setMessage(null); };
  const toggle = (code: string) => edit({ keepOriginal: draft.keepOriginal.includes(code) ? draft.keepOriginal.filter((c) => c !== code) : [...draft.keepOriginal, code] });

  const save = () => {
    const body: Record<string, unknown> = {
      kodi: { host: draft.host, port: draft.port, tcpPort: draft.tcpPort, user: draft.user, ...(draft.password ? { password: draft.password } : {}) },
      titles: { keepOriginal: draft.keepOriginal },
      downloadStation: dsBody(),
      dryRun: draft.dryRun,
      shield: { enabled: draft.shieldOn, port: draft.shieldPort, app: draft.shieldApp },
      quality: { preferHdr: draft.preferHdr },
      tmdb: { language: draft.tmdbLanguage, ...(draft.token ? { token: draft.token } : {}) },
    };
    api.saveSettings(body)
      .then((s) => { setSaved(s); setDraft(toDraft(s)); setDirty(false); refresh(); })
      .catch((e: Error) => setMessage({ kind: 'error', text: e.message }));
  };

  function dsBody() {
    return { url: draft!.dsUrl, user: draft!.dsUser, ...(draft!.dsPassword ? { password: draft!.dsPassword } : {}) };
  }
  const testDs = () => {
    setDs(null);
    const go = dirty ? api.saveSettings({ downloadStation: dsBody() }) : Promise.resolve(saved);
    go.then(() => api.testDownloadStation()).then(setDs).catch((e: Error) => setDs({ connected: false, problem: e.message }));
  };

  // Removing a saved secret saves at once: it is its own action, not part of the draft.
  const forget = (body: unknown) => {
    api.saveSettings(body)
      .then((s) => { setSaved(s); setDraft(toDraft(s)); setDirty(false); refresh(); })
      .catch((e: Error) => setMessage({ kind: 'error', text: e.message }));
  };

  const test = () => {
    setTesting(true);
    setKodi(null);
    const go = dirty ? api.saveSettings({ kodi: { host: draft.host, port: draft.port, user: draft.user, ...(draft.password ? { password: draft.password } : {}) } }) : Promise.resolve(saved);
    go.then(() => api.testKodi()).then(setKodi).catch((e: Error) => setKodi({ connected: false, problem: e.message })).finally(() => setTesting(false));
  };

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">Settings</p>
          <h1>How muthur works</h1>
        </div>
        <div className="actions">
          {dirty && <span className="status small muted"><Dot kind="dot-warning" />Unsaved changes</span>}
          <button className="btn btn-primary" type="button" onClick={save} disabled={!dirty}>Save</button>
        </div>
      </header>
      {message && <div className={`banner banner-${message.kind}`} role="alert">{message.text}</div>}

      <section className="panel form" aria-labelledby="changes-h">
        <h2 id="changes-h" style={{ margin: 0, fontSize: '1.15rem', fontWeight: 650 }}>Changes to the library</h2>
        <label className="choice">
          <input type="checkbox" checked={draft.dryRun} onChange={(e) => edit({ dryRun: e.target.checked })} />
          <span><strong>Dry run: plan only.</strong> Everything is checked and shown, but nothing is moved, written or quarantined, and the weekly score refresh waits.</span>
        </label>
        <label className="choice">
          <input type="checkbox" checked={draft.preferHdr} onChange={(e) => edit({ preferHdr: e.target.checked })} />
          <span><strong>Duplicates: HDR counts as better.</strong> Off while the TV is SDR; then an HDR copy never wins only for being HDR.</span>
        </label>
      </section>

      <section className="panel form" aria-labelledby="tmdb-h">
        <h2 id="tmdb-h" style={{ margin: 0, fontSize: '1.15rem', fontWeight: 650 }}>TMDB</h2>
        <p className="hint">muthur looks titles up on TMDB. A personal token is free: on themoviedb.org go to Settings, then API, and copy the “API Read Access Token”.</p>
        <div className="actions">
          <span className="status small">
            {saved.tmdb.tokenFrom === 'settings' ? <><Dot kind="dot-success" />A token is saved</>
              : saved.tmdb.tokenFrom === 'install' ? <><Dot kind="dot-success" />A token comes from the install settings (.env)</>
                : <><Dot kind="dot-danger" />No token yet</>}
          </span>
          {saved.tmdb.tokenFrom === 'settings' && !dirty && (
            <button className="btn btn-secondary btn-sm" type="button" onClick={() => forget({ tmdb: { forget: true } })}>Remove the saved token</button>
          )}
        </div>
        <label className="field-label">{saved.tmdb.tokenSet ? 'Replace the token' : 'Token'}
          <input className="field" type="password" autoComplete="off" value={draft.token} onChange={(e) => edit({ token: e.target.value })} />
        </label>
        <label className="field-label">Language of plots, genres and episode titles
          <select className="field" value={draft.tmdbLanguage} onChange={(e) => edit({ tmdbLanguage: e.target.value })}>
            {METADATA_LANGUAGES.map((code) => <option key={code} value={code}>{metadataLanguage(code)}</option>)}
          </select>
        </label>
      </section>

      <section className="panel form" aria-labelledby="kodi-h">
        <h2 id="kodi-h" style={{ margin: 0, fontSize: '1.15rem', fontWeight: 650 }}>Kodi on the Shield</h2>
        <p className="hint">In Kodi: Settings, Services, Control, then turn on “Allow remote control via HTTP” and set a username and password.</p>
        <label className="field-label">The Shield’s address
          <input className="field" type="text" placeholder="for example 192.168.1.20" value={draft.host} onChange={(e) => edit({ host: e.target.value })} />
        </label>
        <div className="pair">
          <label className="field-label">Port<input className="field" type="text" inputMode="numeric" value={draft.port} onChange={(e) => edit({ port: e.target.value })} /></label>
          <label className="field-label">Username<input className="field" type="text" autoComplete="off" value={draft.user} onChange={(e) => edit({ user: e.target.value })} /></label>
        </div>
        <label className="field-label">{saved.kodi.passwordSet ? 'Password (saved; type to replace it)' : 'Password'}
          <input className="field" type="password" autoComplete="off" value={draft.password} onChange={(e) => edit({ password: e.target.value })} />
        </label>
        <label className="field-label">Port for notifications
          <input className="field" type="text" inputMode="numeric" value={draft.tcpPort} onChange={(e) => edit({ tcpPort: e.target.value })} />
          <span className="hint">9090 unless you changed it in Kodi. muthur hears through it when something was watched.</span>
        </label>
        <div className="actions">
          <button className="btn btn-secondary btn-sm" type="button" onClick={test} disabled={testing || !draft.host}>{testing ? 'Testing…' : 'Test the connection'}</button>
          {kodi && (kodi.connected
            ? <span className="status small"><Dot kind="dot-success" />Connected · Kodi {kodi.version}</span>
            : <span className="status small"><Dot kind="dot-danger" />{kodi.problem}</span>)}
        </div>
        <ShieldSettings draft={draft} edit={edit} />
      </section>

      <section className="panel form" aria-labelledby="ds-h">
        <h2 id="ds-h" style={{ margin: 0, fontSize: '1.15rem', fontWeight: 650 }}>Download Station</h2>
        <p className="hint">
          After a download is moved into the library, muthur removes its finished task from Download Station, so it doesn’t keep pointing at files
          that are gone. Use the DSM account that adds the downloads, because Download Station only shows an account its own tasks; it must not use
          two-step verification. Leave this empty to keep tasks as they are.
        </p>
        <label className="field-label">The NAS’s address
          <input className="field" type="text" placeholder="for example http://192.168.1.10:5000" value={draft.dsUrl} onChange={(e) => edit({ dsUrl: e.target.value })} />
        </label>
        <div className="pair">
          <label className="field-label">DSM account<input className="field" type="text" autoComplete="off" value={draft.dsUser} onChange={(e) => edit({ dsUser: e.target.value })} /></label>
          <label className="field-label">{saved.downloadStation.passwordSet ? 'Password (saved)' : 'Password'}
            <input className="field" type="password" autoComplete="off" value={draft.dsPassword} onChange={(e) => edit({ dsPassword: e.target.value })} />
          </label>
        </div>
        <div className="actions">
          <button className="btn btn-secondary btn-sm" type="button" onClick={testDs} disabled={!draft.dsUrl || !draft.dsUser}>Test the connection</button>
          {(saved.downloadStation.url || saved.downloadStation.user) && !dirty && (
            <button className="btn btn-secondary btn-sm" type="button" onClick={() => forget({ downloadStation: { forget: true } })}>Forget this account</button>
          )}
          {ds && (ds.connected
            ? <span className="status small"><Dot kind="dot-success" />Connected · {ds.tasks} tasks</span>
            : <span className="status small"><Dot kind="dot-danger" />{ds.problem}</span>)}
        </div>
      </section>

      <section className="panel form" aria-labelledby="titles-h">
        <h2 id="titles-h" style={{ margin: 0, fontSize: '1.15rem', fontWeight: 650 }}>Which films keep their original title?</h2>
        <p className="hint">Plots and genres come in the language chosen under TMDB. A language that’s on keeps the original title (Aguirre, der Zorn Gottes); one that’s off gets the English title (Spirited Away).</p>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {ALL_LANGUAGES.map((code) => (
            <button key={code} type="button" className="chip" aria-pressed={draft.keepOriginal.includes(code)} onClick={() => toggle(code)}>
              {language(code)}
            </button>
          ))}
        </div>
      </section>

      <PasswordSettings />

      <section className="panel form" aria-labelledby="dirs-h">
        <h2 id="dirs-h" style={{ margin: 0, fontSize: '1.15rem', fontWeight: 650 }}>Folders</h2>
        <p className="hint">Set when muthur was installed on the NAS.</p>
        <ul className="rows">
          <li><span>Finished downloads</span><span className="mono small" style={{ overflowWrap: 'anywhere' }}>{libraryPath(saved.paths.downloads)}</span></li>
          <li><span>TV</span><span className="mono small" style={{ overflowWrap: 'anywhere' }}>{libraryPath(saved.paths.tv)}</span></li>
          <li><span>Film</span><span className="mono small" style={{ overflowWrap: 'anywhere' }}>{libraryPath(saved.paths.film)}</span></li>
        </ul>
      </section>
      <Footer />
    </div>
  );
}
