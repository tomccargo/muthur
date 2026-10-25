import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@fontsource-variable/figtree';
import '@fontsource-variable/bricolage-grotesque';
import './theme.css';
import './app.css';
import { App } from './App';
import { installMotion } from './motion';

installMotion(document.getElementById('root')!);
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
