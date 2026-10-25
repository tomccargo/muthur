// System / Dark / Light (DESIGN.md §5). The choice is remembered when storage allows it.
import { useState } from 'react';

export type ThemeChoice = 'system' | 'dark' | 'light';
const KEY = 'muthur.theme';

function read(): ThemeChoice {
  try {
    const v = localStorage.getItem(KEY);
    return v === 'dark' || v === 'light' ? v : 'system';
  } catch {
    return 'system';
  }
}

export function useTheme(): [ThemeChoice, (t: ThemeChoice) => void] {
  const [theme, setTheme] = useState<ThemeChoice>(read);
  const choose = (t: ThemeChoice) => {
    setTheme(t);
    if (t === 'system') delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = t;
    try {
      if (t === 'system') localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, t);
    } catch {
      // Not remembered; the choice still applies for this visit.
    }
  };
  return [theme, choose];
}
