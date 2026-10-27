import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@fontsource-variable/figtree';
import '@fontsource-variable/bricolage-grotesque';
import './theme.css';
import './app.css';
import { App } from './App';
import { installMotion } from './motion';

// A page open across an update asks for its old parts (the player), which the update removed (27 Oct: Watch stayed
// empty, "disallowed MIME type"). It loads the new version instead, as Vite advises (vite.dev, Load Error Handling);
// once a minute at most, so a part that is really missing can't reload it forever.
window.addEventListener('vite:preloadError', (event) => {
  let last = 0;
  try { last = Number(sessionStorage.getItem('muthur.reloaded') ?? 0); } catch { /* storage blocked: reload anyway */ }
  if (Date.now() - last < 60_000) return;
  try { sessionStorage.setItem('muthur.reloaded', String(Date.now())); } catch { /* as above */ }
  event.preventDefault();
  window.location.reload();
});

installMotion(document.getElementById('root')!);
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
