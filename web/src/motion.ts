// Motion as in Playlist Parser's normal mode (DESIGN.md §6): pages fade and rise, panels ease in as they
// come into view, tiles drop in one after another, numbers count up, and a poster flies into its page.
// Everything is off when the system asks for reduced motion.

const reduced = () => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
export const motionOn = () => !reduced();

// ---- Numbers count up ------------------------------------------------------------------------
// Writes into React's own text node and stops the moment React shows a newer value.
function countUp(el: HTMLElement, delay = 0, duration = 1200) {
  const node = el.childNodes.length === 1 && el.firstChild?.nodeType === Node.TEXT_NODE ? el.firstChild : null;
  const original = node?.nodeValue ?? '';
  const m = original.trim().match(/^(\d[\d,]*)(.*)$/s);
  if (!node || !m) return;
  const target = Number(m[1].replace(/,/g, ''));
  if (!Number.isFinite(target) || target === 0) return;
  const grouped = m[1].includes(',');
  const show = (v: number) => (grouped ? Math.round(v).toLocaleString('en-GB') : String(Math.round(v))) + m[2];
  let written = show(0);
  node.nodeValue = written;
  const t0 = performance.now() + delay;
  const step = (now: number) => {
    if (node.nodeValue !== written) return; // React wrote a newer value: leave it
    const p = Math.min(1, Math.max(0, (now - t0) / duration));
    written = p >= 1 ? original : show(target * (1 - Math.pow(1 - p, 3)));
    node.nodeValue = written;
    if (p < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

// ---- Panels and tiles ease in as they come into view --------------------------------------------
// The player's grid and its Recently added row drop in like Library's posters (27 Oct).
const DROP = '.tiles, .posters, .pl-grid, .pl-row';
const REVEAL = `.panel, .page-head, ${DROP}`;

function reveal(el: HTMLElement) {
  if (el.matches(DROP)) {
    [...el.children].slice(0, 30).forEach((c, i) => (c as HTMLElement).style.setProperty('--i', String(i)));
    if (el.matches('.tiles')) el.querySelectorAll<HTMLElement>('strong').forEach((s, i) => countUp(s, 200 + i * 60));
  } else {
    el.querySelectorAll<HTMLElement>('strong.num').forEach((s) => countUp(s, 150));
  }
  el.dataset.reveal = 'in';
}

export function installMotion(root: HTMLElement) {
  if (typeof IntersectionObserver !== 'function' || typeof MutationObserver !== 'function') return;
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      io.unobserve(e.target);
      reveal(e.target as HTMLElement);
    }
  }, { rootMargin: '0px 0px -8% 0px' });
  const watch = (scope: Element) => {
    const found = [...(scope.matches(REVEAL) ? [scope] : []), ...scope.querySelectorAll(REVEAL)] as HTMLElement[];
    for (const el of found) {
      if (el.dataset.reveal || el.parentElement?.closest('[data-reveal]:is(.panel)')) continue; // nested panels move with their parent
      el.dataset.reveal = 'wait';
      io.observe(el);
    }
  };
  new MutationObserver((records) => {
    if (reduced()) return;
    for (const r of records) r.addedNodes.forEach((n) => n instanceof Element && watch(n));
  }).observe(root, { childList: true, subtree: true });
}

// ---- A poster flies into its page ----------------------------------------------------------------
// The clicked poster and the page's big cover share a view-transition name; the page change waits
// (at most 400 ms) until the new page has drawn its cover.
export const hero = { to: '', src: '' };
let landed: (() => void) | null = null;

export function heroClick(e: React.MouseEvent<HTMLElement>, to: string) {
  const img = e.currentTarget.querySelector('img');
  if (!img || !motionOn()) return;
  hero.to = to;
  hero.src = img.currentSrc || img.src;
  img.style.viewTransitionName = 'hero';
}

// The destination page calls this once its cover is on screen.
export function heroLanded() {
  landed?.();
  landed = null;
  setTimeout(() => { hero.to = ''; hero.src = ''; }, 700);
}

type VT = { startViewTransition?: (cb: () => Promise<void>) => { finished: Promise<void> } };

// Runs a page change inside a view transition (fade and rise; a poster flight when one was clicked).
export function transition(change: () => void) {
  const start = (document as Document & VT).startViewTransition?.bind(document);
  if (!start || !motionOn()) {
    change();
    return;
  }
  start(() => new Promise<void>((done) => {
    change();
    if (!hero.to) return done();
    landed = done;
    setTimeout(() => { if (landed === done) { landed = null; done(); } }, 400);
  }));
}
