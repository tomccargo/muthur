import { useState } from 'react';
import { api } from '../api';
import { Dot } from '../components';

export type ShieldDraft = { shieldOn: boolean; shieldPort: string; shieldApp: string };

// Waking the Shield and starting Kodi (over network debugging). The app list comes from the Shield itself.
export function ShieldSettings({ draft, edit }: { draft: ShieldDraft; edit: (patch: Partial<ShieldDraft>) => void }) {
  const [apps, setApps] = useState<string[] | null>(null);
  const [current, setCurrent] = useState<string | null>(null);
  const [state, setState] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () => {
    setBusy(true);
    setState(null);
    api.shieldApps()
      .then((r) => { setApps(r.apps); setCurrent(r.current); setState({ ok: true, text: `Connected · ${r.apps.length} apps on the Shield` }); })
      .catch((e: Error) => setState({ ok: false, text: e.message }))
      .finally(() => setBusy(false));
  };
  const wake = () => {
    setBusy(true);
    setState(null);
    api.wakeShield()
      .then((r) => setState({ ok: true, text: r.note ?? 'The Shield is awake and Kodi answers.' }))
      .catch((e: Error) => setState({ ok: false, text: e.message }))
      .finally(() => setBusy(false));
  };
  const onScreen = apps?.find((a) => current && a.startsWith(current + '/'));

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, paddingTop: 12, borderTop: '1px solid var(--border)' }}>
      <h3 style={{ margin: 0, fontSize: '1rem', fontWeight: 650 }}>Waking the Shield</h3>
      <p className="hint">
        When you start something that needs Kodi (Apply, Duplicates, a restore) and the Shield sleeps, muthur wakes it and starts Kodi first.
        This uses network debugging (Device Preferences, Developer options). The first time, the TV asks to allow muthur: tick “Always allow”.
        Only things you start wake it; the scheduled checks never do. Waking may switch the TV on and to the Shield (HDMI-CEC).
      </p>
      <label className="choice">
        <input type="checkbox" checked={draft.shieldOn} onChange={(e) => edit({ shieldOn: e.target.checked })} />
        <span>Wake the Shield when Kodi is needed</span>
      </label>
      <div className="pair">
        <label className="field-label">Network debugging port
          <input className="field" type="text" inputMode="numeric" value={draft.shieldPort} onChange={(e) => edit({ shieldPort: e.target.value })} />
        </label>
        <label className="field-label">App to start
          <select className="field" value={draft.shieldApp} onChange={(e) => edit({ shieldApp: e.target.value })}>
            {!draft.shieldApp && <option value="">Choose after reading the Shield’s apps</option>}
            {draft.shieldApp && !(apps ?? []).includes(draft.shieldApp) && <option value={draft.shieldApp}>{draft.shieldApp.split('/')[0]}</option>}
            {(apps ?? []).map((a) => <option key={a} value={a}>{a.split('/')[0]}{a === onScreen ? ' (on screen now)' : ''}</option>)}
          </select>
        </label>
      </div>
      <div className="actions">
        <button className="btn btn-secondary btn-sm" type="button" disabled={busy} onClick={load}>Read the Shield’s apps</button>
        {onScreen && draft.shieldApp !== onScreen && (
          <button className="btn btn-secondary btn-sm" type="button" onClick={() => edit({ shieldApp: onScreen })}>Use the app on screen ({onScreen.split('/')[0]})</button>
        )}
        <button className="btn btn-secondary btn-sm" type="button" disabled={busy || !draft.shieldApp} onClick={wake}>Wake the Shield now</button>
        {busy && <span className="small muted">Talking to the Shield…</span>}
        {state && <span className="status small"><Dot kind={state.ok ? 'dot-success' : 'dot-danger'} />{state.text}</span>}
      </div>
    </div>
  );
}
