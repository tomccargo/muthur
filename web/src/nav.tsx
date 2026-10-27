// A minimal router: three pages don't need a routing library.
import { useEffect, useState, type AnchorHTMLAttributes, type MouseEvent } from 'react';
import { flushSync } from 'react-dom';
import { transition } from './motion';

const listeners = new Set<() => void>();

export function navigate(to: string, { replace = false } = {}) {
  if (replace) history.replaceState(null, '', to);
  else if (to !== location.pathname + location.search) history.pushState(null, '', to);
  // The new page is drawn inside the view transition, so it fades and rises in (motion.ts).
  transition(() => flushSync(() => {
    listeners.forEach((l) => l());
    window.scrollTo(0, 0);
  }));
}

export function useLocation() {
  const [loc, setLoc] = useState(() => ({ path: location.pathname, search: location.search }));
  useEffect(() => {
    const update = () => setLoc({ path: location.pathname, search: location.search });
    listeners.add(update);
    window.addEventListener('popstate', update);
    return () => {
      listeners.delete(update);
      window.removeEventListener('popstate', update);
    };
  }, []);
  return loc;
}

export function Link({ to, onClick: before, ...rest }: { to: string } & AnchorHTMLAttributes<HTMLAnchorElement>) {
  // A caller's onClick runs first (a poster marks itself for the flight), then the page changes here.
  const onClick = (e: MouseEvent<HTMLAnchorElement>) => {
    before?.(e);
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    navigate(to);
  };
  return <a href={to} {...rest} onClick={onClick} />;
}
