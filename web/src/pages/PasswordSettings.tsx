import { useState } from 'react';
import { api, askToSignIn } from '../api';
import { Dot } from '../components';

// muthur's own password: change it (every other browser signs in again), or sign this browser out.
export function PasswordSettings() {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [busy, setBusy] = useState(false);
  const [state, setState] = useState<{ ok: boolean; text: string } | null>(null);

  const change = () => {
    setBusy(true);
    setState(null);
    api.changePassword(current, next)
      .then(() => { setCurrent(''); setNext(''); setState({ ok: true, text: 'Changed. Other browsers sign in again with the new password.' }); })
      .catch((e: Error) => setState({ ok: false, text: e.message }))
      .finally(() => setBusy(false));
  };
  const signOut = () => { api.logout().finally(() => askToSignIn('login')); };

  return (
    <section className="panel form" aria-labelledby="password-h">
      <h2 id="password-h" style={{ margin: 0, fontSize: '1.15rem', fontWeight: 650 }}>Password</h2>
      <p className="hint">A new password signs every other browser out.</p>
      <div className="pair">
        <label className="field-label">Current password
          <input className="field" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />
        </label>
        <label className="field-label">New password
          <input className="field" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
        </label>
      </div>
      <div className="actions">
        <button className="btn btn-secondary btn-sm" type="button" disabled={busy || !current || next.length < 8} aria-busy={busy} onClick={change}>Change the password</button>
        <button className="btn btn-secondary btn-sm" type="button" onClick={signOut}>Sign out</button>
        {state && <span className="status small"><Dot kind={state.ok ? 'dot-success' : 'dot-danger'} />{state.text}</span>}
      </div>
    </section>
  );
}
