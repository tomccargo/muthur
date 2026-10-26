# muthur: design system and UI rules

The look and the rules of muthur's web UI. The **look** follows *Playlist Parser*: a dark-first media app with a side rail, an amber accent, Figtree and Bricolage Grotesque, posters as the main visual. The **rules** are adapted from the *PXL CloudLabs* dashboard design system: one primary action per view, status dots, honest status, readable labels.

What muthur does not take from either:
- Playlist Parser's playful motion (confetti, disco ball, cursor trail, shader backdrops, count-up numbers, flying covers). See §6 for the motion that is allowed.
- CloudLabs' flat GitHub look (3px corners, no pill buttons). Where the two clash, Playlist Parser's look wins.

The UI is built in **React + TypeScript** (Vite). Playlist Parser is GPL-3.0 and muthur is MIT, so only its *design values* (colours, sizes, fonts, layout) are reused here. Its code is not copied: every muthur component is written for muthur.

Section numbers are referenced from code comments; do not renumber.

---

## 1. Principles

### 1.1 Tonal surfaces, few boxes

- A **box** is a border on all four sides; a single-side border is a divider and is fine.
- The page (`--bg`) holds **panels** (`--surface`, one border, `--radius`). Inside a panel, group with whitespace (12-24px) and dividers, or a tonal step (`--surface-muted`). Never another bordered box.
- **Never nest three boxes.** A dialog, a panel inside it and a bordered control inside that is a prison.
- Check that the tones really differ in **both** themes before dropping a border.

### 1.2 One primary button per view

- **Exactly one** solid `.btn-primary` per view or dialog that has an action: the thing the view is for. *Check downloads* on the dashboard, *Apply 17 ready items* in the inbox, *It's Solaris (1972)* in review, *Keep 1, quarantine 2* on a duplicate group, *Apply 3 fixes* on Health, *Save* in settings. A view that is only for reading (History) has none.
- Everything else is `.btn-secondary`, `.btn-ghost` or `.btn-link`.
- An action repeated per row is never primary.
- **Destructive or hard-to-undo actions** are never a bare solid button. They sit behind `.btn-danger-outline` and are confirmed in the page (§7.3). Examples: *Empty quarantine*, *Restore watched status* (it writes to Kodi), *Undo whole run*.
- A form has **one** action row.

### 1.3 Status dots, not pill capsules

- In lists, tables and detail rows, status is a `.status` with a `.dot` and plain mixed-case text: `● Ready`, `● Needs review`, `● Ignored`, `● Moved`.
- No uppercase pill badges repeated on every row. Pills are only for **counters in navigation** (the rail's *Review 1*) and for **tags a reader filters by** (a season, a language).

### 1.4 Navigation

- **Five sections, one per job (0.24):** *Dashboard, Downloads, Library, History, Settings*. *Downloads* holds *Inbox* and *Review* as tabs; *Library* holds *Shows and films*, *Duplicates* and *Health*. Each page keeps its own address (`/review`, `/health`), and its tab is marked like the section.
- Desktop (wider than 960px): a **side rail** with icon + label per section; the current section is marked with `--accent-soft`. A counter pill sits after a section and after a tab only when it isn't zero (a section's is the sum of its tabs').
- Phone (960px or narrower): a **top bar** (brand, a status dot for Kodi and the watched backup, the theme switch) and a **bottom tab bar** with all five sections. Material 3 keeps a bottom bar to five destinations or fewer.
- A **skip link** ("Skip to the page") is the first thing a keyboard reaches.
- **One name per thing:** the rail item, the page title and every link to it use the same word. *Review* is never also *Queue* or *To check*.

### 1.5 The UI never describes behaviour the system does not have

The most expensive kind of UI bug. Three shapes: a **dead field** (a setting no code reads), a **dead promise** (a message promising a process that does not exist), and a **control that breaks what it claims to protect**. The fix is never a reword: give the system the behaviour, or remove the control and say why.

muthur examples:
- In **dry run**, every result says that nothing was moved (*Planned, not moved: dry run is on*). A plan is never shown as if it happened.
- **Status is computed from facts every time it is shown:** *Kodi connected* comes from a live JSON-RPC ping, not from the last time it worked. *Watched status backed up* says when (*Backed up 21:14*).
- **Data that is a cache says how old it is:** IMDb scores say when the datasets were downloaded, TMDB data when it was fetched.
- A failure stays on screen with its way out (*Try again*, *Open settings*), never only in a toast.

### 1.6 The UI never points a reader at this repository

- No `DESIGN.md`, `ARCHITECTURE.md`, milestone numbers or section numbers in anything on screen.
- No container paths (`/data/TV/…`). Show paths as the reader knows them: the library-relative path (`TV/Foundation (2021)/Season 01/`) or the share path from the settings.
- A message says **what happened and what to do**: *"Kodi didn't answer. Is the Shield on, and is 'Allow remote control via HTTP' enabled?"*

### 1.7 A stored value is not a label

- Code words never reach the screen as is. Parser flags get sentences: `absolute-number` becomes *Numbered 1, 2, 3 without seasons*, `broken-episode-number` becomes *Episode number is damaged (S10E-1)*. TMDB `first_air_date` becomes *2021*.
- Every enum has a label map in one place; an unknown value falls back to itself rather than a blank.
- **The heading asks, the cell answers.** No repeating the column name in every cell; an empty value is a dash.
- **Name what happens to the reader's files**, not the record. *Move to quarantine*, not *Delete duplicate*. *Rename to S01E01*, not *Fix flag*.
- IDs and release names are shown only where they help a decision: a release name in monospace as the file it is, a TMDB or IMDb ID as a link to that site.

### 1.8 Forms

- **One column width** for the whole form (`max-width: 640px`); every control fills it.
- **Fields in the order values derive.** A value muthur can work out (the target path, the title rule's outcome) is **stated as text**, not asked in an input.
- A pair read together (port and username) may share a row (`grid-template-columns: minmax(0, 1fr) minmax(0, 1fr)`).
- Rare options go under a closed **Advanced** disclosure; when one is on, a line outside says so.
- Unsaved edits are said (*Unsaved changes*); a saved form says nothing.

### 1.9 Ask the question the reader is asking

- One question per decision, with answers that say what happens. The review screen asks *Which film is this?*, not *Select candidate*.
- A control starting with *Also*, *And* or *Additionally* is a second question in disguise.

### 1.10 Say where data comes from

- TMDB requires attribution: the footer says *Data and images from TMDB. This product uses the TMDB API but is not endorsed or certified by TMDB.*
- Scores name their source next to the number: *IMDb 8.4*, *TMDB 7.9*. Never a bare number.

### 1.11 Status, not explanations (0.25)

- A page shows **numbers, status and actions**. What a panel means is explained once, in Settings or the docs, not on every visit. *162 remembered*, not *162 shows remembered. New episodes of a remembered show go straight into its folder, without a search.*
- A **problem keeps its sentence and its way out** (§1.5): a paused backup, a folder that can't be read, Kodi that doesn't answer (*Off (asleep, or Kodi closed)* with *Wake the Shield*).
- A panel with **nothing to say is left out**: the Folders panel appears only when a folder has a problem.
- Tiles are a label and a number; a status line joins its facts with ` · ` (*Backed up 20:38 · 783 of 5,335 watched · hourly*).

---

## 2. Design tokens

Declared once, in `web/src/theme.css`, under `:root` (dark) and again for light (§5). **The token block is the only place a colour literal may appear.** Components use tokens only, so both themes stay correct.

### Surfaces and text

| Token | Dark (default) | Light | Use |
| :--- | :--- | :--- | :--- |
| `--bg` | `#0e1210` | `#d4dad6` | Page background |
| `--surface` | `#161b18` | `#ffffff` | Panels, rail, tiles |
| `--surface-muted` | `#1f2622` | `#e2e7e4` | Tonal step inside a panel, hover, segmented control |
| `--surface-raised` | `#1b211e` | `#ffffff` | Menus, dialogs |
| `--border` | `#2b342f` | `#9ba6a0` | Panel edge, dividers (2.5:1 on a panel) |
| `--border-strong` | `#636f68` | `#6f7b74` | Inputs, secondary buttons (at least 3:1 on what is behind them, WCAG 1.4.11) |
| `--text` | `#ecf1ed` | `#131a16` | Body text |
| `--muted` | `#a1ada5` | `#535f58` | Secondary text (4.5:1 or better on `--surface`) |
| `--faint` | `#6f7b74` | `#66726b` | Decoration only, never text a reader needs |

The light ramp is inverted against dark (grey page, white panels), so a panel reads as raised in both themes.

### Accent

| Token | Dark | Light | Use |
| :--- | :--- | :--- | :--- |
| `--accent` | `#f0a95b` | `#eb9a3f` | Primary button fill, current-section marker |
| `--accent-hover` | `#f6bd7e` | `#e08a2a` | Primary hover |
| `--accent-ink` | `#2a1606` | `#2a1606` | Text on `--accent` |
| `--accent-text` | `#f4b872` | `#94490a` | Links, eyebrow labels |
| `--accent-soft` | `#2c2318` | `#fbe1c2` | Current rail item, selected card |
| `--accent-strong` | `#f8cd98` | `#6b3404` | Text on `--accent-soft` |
| `--focus` | `#8ab4ff` | `#1a5fd0` | Focus ring |

Amber is muthur's only accent, which also nods to the amber terminal of the Nostromo's computer.

### Status and data

| Token | Dark | Light | Use |
| :--- | :--- | :--- | :--- |
| `--good` | `#5fd38d` | `#1a7f45` | `.dot-success`, positive figures |
| `--warn-bg` / `--warn-text` | `#33290f` / `#f5d58e` | `#fff3d4` / `#5c4400` | Warning banners, `.dot-warning` (`--warn-text`), rail counters |
| `--danger-bg` / `--danger-text` | `#3b1c18` / `#ffb3a7` | `#fdecec` / `#8a1c1c` | Error banners, `.dot-danger` (`--danger-text`) |
| `--mark` | `#f0a95b` | `#b85f0b` | Bars, meters, score bars (3:1 or better on `--surface`) |
| `--track` | `#262e2a` | `#b4beb8` | Empty part of a bar |
| `--poster-bg` | `#0a0c0b` | `#1a1f1c` | Behind posters and stills |

No hand-rolled `rgba()` status colours.

### Type

- **Body:** `Figtree Variable`, then `ui-sans-serif, system-ui, 'Segoe UI', sans-serif`. 15px, line height 1.5.
- **Display:** `Bricolage Grotesque Variable` for `h1`–`h4`, tile numbers and the brand. `h1` 700, `h2`/`h3` 650, letter-spacing `-0.01em`, `text-wrap: balance`.
- **Monospace:** `ui-monospace, 'Cascadia Code', Consolas, monospace` for file names, paths, release names, IDs and durations.
- Numbers in tables and tiles use `font-variant-numeric: tabular-nums`.
- Both fonts are self-hosted through `@fontsource-variable/*` (SIL OFL 1.1). No CDN: the app runs on a LAN and must work without internet for its own chrome.

### Shape

- `--radius: 12px` for panels, tiles and dialogs; `--radius-sm: 8px` for banners, inputs, posters and menu rows.
- Buttons, counters and segmented controls are **pills** (`999px`).
- `--shadow` only on menus and dialogs, never on panels.
- Page: `max-width: 1180px`, padding `28px 32px 64px` (desktop), `20px 16px 48px` (phone).

---

## 3. Buttons (the complete set)

| Class | What it is |
| :--- | :--- |
| `.btn-primary` | The single solid action of the view (§1.2) |
| `.btn-secondary` | Standard and toolbar actions: outlined with `--border-strong` |
| `.btn-ghost` | No fill; *← Library*, icon buttons |
| `.btn-link` | Looks like a link, behaves as a button |
| `.btn-danger-outline` / `.btn-danger` | Destructive: outline on the page, solid only inside its confirmation (§7.3) |
| `.btn-sm` | Small size: everything in a page head except the primary, and buttons inside rows |
| `.icon-btn` | Square, icon only, always with `aria-label` and `title` |
| `.seg` | Segmented control (`aria-pressed` buttons): the theme switch, *TV / Film* |

No other variants. A disabled button that has a standing reason is `aria-disabled="true"` with the reason in a hint, not `disabled`, so the reason stays reachable by keyboard.

---

## 4. Status dots (the complete set)

| Dot | muthur meaning |
| :--- | :--- |
| `.dot-success` | Ready to apply, moved, Kodi connected, watched status backed up |
| `.dot-warning` | Needs review, dry run is on, job running, score refresh overdue |
| `.dot-danger` | Failed, video file missing, Kodi unreachable, watched-status backup paused by the mass-change guard, **Suspicious** (a program or disc image named like an episode or film) |
| `.dot-warning` (also) | **Packed**: a download inside an archive, which muthur doesn't unpack |
| `.dot-neutral` | Ignored (not video), skipped, no ground truth |
| `.dot-info` | A notice; prefer neutral |

---

## 5. Theming

- **Dark is the default.** Posters and stills read best on dark, as in Playlist Parser.
- A three-way **segmented switch** in the rail footer: *System · Dark · Light* (icons: monitor, moon, sun). *System* follows `prefers-color-scheme`. A choice is stored in `localStorage` (`muthur.theme`), wrapped in `try`/`catch`: private windows and blocked storage must still work, the choice just isn't remembered.
- `:root[data-theme="light"|"dark"]` pins a theme. A tiny inline script in `index.html` sets it before the stylesheet paints, so there is no flash.
- No colour transition on theme change.

---

## 6. Motion

Playlist Parser's normal mode (0.26), in `web/src/motion.ts` and `app.css`; not its Zen or disco modes.

- **Pages** change inside a view transition: the old page fades and settles (220 ms, slight blur), the new one fades in rising 28 px (420 ms). The rail, top bar and tab bar stay still. Browsers without view transitions switch instantly.
- **Panels and page heads** rise 28 px and fade in as they come into view (700 ms, soft ease-out), once per page visit.
- **Tiles and posters** drop in one after another, 60 ms apart, with a slight overshoot (600 ms).
- **Numbers** in tiles and panels count up from 0 (1.2 s, ease-out) and always end on the real value; a newer value from the server wins at once.
- **A poster flies** into its show or film page (560 ms); the page change waits at most 400 ms for the cover.
- **Hover and press:** background, border and colour in 150 ms; buttons, tiles and posters press in to 97 %.
- **Bars and job progress** move with real progress; a skeleton shimmers while a list loads.

**Not allowed:** confetti, disco, cursor trails, shader or animated backdrops, intro sequences, parallax, and anything that loops while the page is idle.

**Reduced motion:** when the system asks for it (`prefers-reduced-motion: reduce`), every transition and animation is off, the page change and the count-up included.
---

## 7. Application chrome

### 7.1 Rail and bars

- **Brand** at the top of the rail: the mark plus *MU/TH/UR* in the display font, and *muthur* in small muted text beneath.
- **Rail footer**, separated by a top divider:
  - Kodi's connection (`● Shield · Kodi 21.3`, or `● Kodi unreachable` with *Check*).
  - Dry run (`● Dry run on`, only when on).
  - Watched-status backup (`● Backed up 21:14`).
  - The theme switch.
- On a phone, a status dot in the top bar stands for the footer: green when Kodi answers and the backup follows it, red otherwise; it opens Settings.

### 7.2 Way back

Inside a show, a movie or a duplicate group: **← Library** (or **← Duplicates**) as a ghost button at the start of the page. Not a breadcrumb that grows.

### 7.3 Confirmations are asked in the page

- Never `window.confirm`, `alert` or `prompt`.
- The title is the question (*Move 2 copies of Dune (2021) to quarantine?*); the button is the action (*Move to quarantine*), never *OK* or *Yes*.
- A destructive answer is the solid `.btn-danger`, and **Cancel has the focus**.
- The body says what will happen in this case, computed: which files, how big, and what stays (*The 10.5 GB WEB-DL copy stays and is renamed to …*).

### 7.4 Dialogs

Head, scrolling body, foot. Only the body scrolls, so the buttons stay on screen. Focus is trapped while open and returns to the trigger on close. Escape closes.

### 7.5 Messages in place

A result appears where the action was taken (under the button or at the top of its panel) and survives a redraw. Not a toast that disappears, and not at the top of the page out of sight.

### 7.6 Waiting (0.27)

Every wait shows itself, the same way everywhere (`components.tsx`):
- **The button pressed spins** (`aria-busy="true"` draws the ring) until its request is answered; a second press does nothing meanwhile. Only that button spins: a section with several actions keeps one busy key, never one shared flag.
- **A long wait counts** (*Waking the Shield… 12 s*) after 3 seconds.
- **A job** shows its bar on the page (indeterminate until it has counted its work), its step and count in the rail on every page, and a spinning dot in the phone's top bar. Jobs started meanwhile wait in line (*Next: …*).
- **A page loading** shows shimmering placeholders where its data will be; a failed load says why, with *Try again*.
- **Busy always clears**, on success and on error, and the result stays where the action was taken (§7.5).

---

## 8. Media rules

- **Posters** are 2:3 with `--radius-sm`, on `--poster-bg`. A missing poster gets a placeholder: the title's initials on a tint derived from the title, never a broken image.
- **Stills and episode thumbnails** are 16:9.
- **Poster grids:** `grid-template-columns: repeat(auto-fill, minmax(128px, 1fr))`, with title and year under the poster (title on two lines at most, ellipsis, full title in `title`).
- **Scores:** source, value and votes, the value in the display font: *IMDb **8.4** · 41k votes*. A score muthur left out on purpose (numbering mismatch) says so: *No IMDb score: IMDb numbers this season differently*.
- **Runtimes** as *2 h 46 m*; **sizes** as *10.5 GB*; **dates** as *Sat 24 Oct* (this year) or *24 Oct 2025*.
- **File names and paths** in monospace, ellipsised in the middle (the end of a name, the release group and extension, matters), with the full value in `title`.
- **Original titles** follow the title rule in the settings; when the shown title isn't the original, the original is shown once on the detail page in `--muted`.

---

## 9. Layout rules

- Grid tracks are `minmax(0, 1fr)`, never a bare `1fr` (a long file name would widen the page on a phone).
- The page never scrolls sideways at 375px. Tables that can grow scroll inside their own panel.
- **Only short values stay on one line:** durations, sizes, dates, scores, status dots, headings. File names ellipsise; sentences wrap.
- Touch targets are at least 44px on phones (rail rows, tab bar, buttons).
- Every interactive thing is a real `<button>`, `<a href>` or `<input>` with a `<label>`. Icon-only buttons have `aria-label`. Visible focus (`:focus-visible`, 3px `--focus` ring, offset 2px).

---

## 10. Checks

Planned with the web UI (architecture, milestone 2 onwards), modelled on the CloudLabs design spec: a Playwright test opens every view against a mock API at 375px and 1280px, in both themes, and fails on:
- page or console errors
- a page that scrolls sideways
- more than one primary button on a view, or none on a view that has an action
- a raw parser flag, container path or TMDB field name on screen
- a corner rounder than 12px
- a missing TMDB attribution in the footer
- any animation running with `prefers-reduced-motion: reduce`

Built (2026-10-25): `tests/test_ui.py` runs these checks with Playwright on every push, against sample data that includes a long path without hyphens and long release names. It is skipped locally when Playwright or the built UI is missing. Its first run caught the Inbox and Settings showing container paths that didn't wrap on a phone.
