import { useState, type FormEvent } from 'react';
import { api, type AuthMode } from '../api';

// The first visit chooses muthur's password; after that a browser signs in with it (ARCHITECTURE.md §14).
export function SignIn({ mode, onDone }: { mode: AuthMode; onDone: () => void }) {
  const [password, setPassword] = useState('');
  const [again, setAgain] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const setup = mode === 'setup';

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (setup && password !== again) {
      setError('The two passwords differ.');
      return;
    }
    setBusy(true);
    setError(null);
    (setup ? api.setup(password) : api.login(password))
      .then(onDone)
      .catch((x: Error) => setError(x.message))
      .finally(() => setBusy(false));
  };

  return (
    <main className="main" id="main" style={{ marginLeft: 0 }}>
      <div className="page" style={{ maxWidth: 460 }}>
        <header className="page-head">
          <div>
            <p className="eyebrow">muthur</p>
            <h1>{setup ? 'Choose a password' : 'Sign in'}</h1>
            <p className="lede">
              {setup
                ? 'muthur moves, renames and deletes files. A password keeps others on your network, and other websites you visit, from doing that through this page.'
                : 'muthur asks once per browser, and again after 30 days without a visit.'}
            </p>
          </div>
        </header>
        <form className="panel form" onSubmit={submit}>
          <label className="field-label">Password
            <input className="field" type="password" autoComplete={setup ? 'new-password' : 'current-password'} autoFocus
              value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
          {setup && (
            <label className="field-label">The same password again
              <input className="field" type="password" autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} />
            </label>
          )}
          {error && <div className="banner banner-error" role="alert">{error}</div>}
          <div className="actions">
            <button className="btn btn-primary" type="submit" disabled={busy || !password || (setup && !again)}>
              {setup ? 'Save the password' : 'Sign in'}
            </button>
          </div>
          <p className="hint">
            {setup ? 'At least 8 characters. ' : ''}
            Forgotten? In Container Manager, open muthur’s terminal and type <span className="mono">muthur password</span> to choose a new one.
          </p>
        </form>
      </div>
    </main>
  );
}
