Revamp the UI of this Next.js app ("Subtitle Maker") to the Vercel dashboard / shadcn/ui visual language, implemented in plain CSS/SCSS with CSS custom properties (no Tailwind, no component library install — hand-build the shadcn look). Keep the brand green as the primary accent color; everything else moves to a neutral zinc palette (replace the current cream/beige background). Do not change any data-fetching, WebDAV scanning, queue, or translation logic — visual and structural styling only.

1. DESIGN TOKENS (styles/tokens.scss)
Light mode (:root):
--background: #ffffff
--surface: #fafafa (card/table background)
--foreground: #09090b
--muted: #f4f4f5
--muted-foreground: #71717a
--border: #e4e4e7
--input: #e4e4e7
--ring: #146c4a
--primary: #146c4a        // sample the exact hex from the current logo/breadcrumb green and use that instead of this placeholder
--primary-foreground: #f4faf7
--accent: #ecfdf5         // pale green for badges/hover states tied to primary
--accent-foreground: #146c4a
--destructive: #ef4444
--destructive-foreground: #fafafa
--radius: 10px

Dark mode ([data-theme="dark"]):
--background: #09090b
--surface: #18181b
--foreground: #fafafa
--muted: #27272a
--muted-foreground: #a1a1aa
--border: #27272a
--input: #27272a
--ring: #34d399
--primary: #34d399
--primary-foreground: #052e1c
--accent: #052e1c
--accent-foreground: #34d399

Spacing: 4/8/12/16/24/32/48/64px as --space-1 to --space-8.
Radius: --radius-sm 6px, --radius-md 8px, --radius-lg 10px, --radius-full 9999px.
Shadows: --shadow-sm 0 1px 2px rgba(0,0,0,.05); --shadow-md 0 2px 8px rgba(0,0,0,.08); --shadow-lg 0 8px 24px rgba(0,0,0,.12).

2. TYPOGRAPHY
Replace the current serif display wordmark with Geist Sans (next/font, fallback Inter), weight 700, letter-spacing -0.02em, size 28px — no serif anywhere. Body/UI text Geist Sans 400/500. Geist Mono for the resolution/codec string in the breadcrumb (e.g. "1080p ATVP WEB-DL x265...") since it's technical metadata. Scale: 12px table headers/uppercase labels, 13px table body, 14px default UI, 15px tagline, 20px section headers.

3. ICONS — replace every icon with lucide-react, stroke-width 1.75, color via currentColor:
- Logo mark: keep the green rounded-square container (--radius-lg), swap the glyph for a Lucide `Captions` or `Subtitles` icon, white, 20px.
- Settings button: `Settings` icon, 16px, left of the label, remove the arrow glyph or replace with `ChevronRight` at 14px trailing.
- Breadcrumb separator: replace "/" with `ChevronRight` at 14px, var(--muted-foreground).
- Search input: `Search` icon, 16px, absolutely positioned inset-left with 12px padding, var(--muted-foreground), turns var(--foreground) on focus.
- Table checkboxes: custom 16px box, --radius-sm, 1px solid var(--border); checked state = var(--primary) fill with Lucide `Check` icon at 12px, white.
- Date column sort indicator: `ArrowDown`/`ArrowUp` 12px next to the header label, only visible on the active sort column.
- Queue toast spinner: `LoaderCircle` 16px with a CSS `spin` keyframe animation (1s linear infinite), var(--primary).
- Queue toast actions: `Trash2` 14px (destructive on hover) and `Minus` 14px for collapse, both as 28px ghost icon-buttons with var(--radius-sm) hover background var(--muted).
- Split CTA button dropdown: `ChevronDown` 16px, inside its own 32px segment separated by a 1px vertical divider (rgba(255,255,255,.2) on the green button).
- Floating avatar button (bottom-left): keep circular, --radius-full, 1px border, --shadow-md, 44px diameter.

4. COMPONENT RESTYLING
- Header: flex row, logo+wordmark left-aligned with tagline in var(--muted-foreground) below at 15px; Settings as an outline button (1px solid var(--border), --radius-md, height 36px, padding-inline 14px) top-right.
- Breadcrumb bar: 14px, current segment var(--primary) medium weight, parent segment var(--muted-foreground), hover underline.
- Search input: height 36px, --radius-md, 1px solid var(--input), full width on its row, focus = 2px var(--ring) ring with 2px offset, no default outline.
- Table: header row 12px uppercase var(--muted-foreground), letter-spacing 0.04em, no visible header background — just a 1px bottom border on the whole header row; body rows 56px height, 1px solid var(--border) between rows, hover background var(--muted), file name 14px medium var(--foreground), size/date 13px var(--muted-foreground) tabular-nums.
- Queue toast/popover: anchor bottom-right of viewport (or the triggering row) as a floating card, var(--surface) background, 1px solid var(--border), --radius-lg, --shadow-lg, max-width 360px; header row = spinner + "X done · Y failed" (13px var(--muted-foreground)) and "N active" (14px medium var(--foreground)) on one line, trash/minus icons right-aligned; below, a divider, then per-item rows with truncated filename (13px, ellipsis overflow) and a status pill.
- Status pill ("SEARCHING"): --radius-full, padding 2px 8px, 11px uppercase letter-spacing 0.03em, background var(--accent), color var(--accent-foreground), font-weight 600.
- Footer disclaimer text: 13px var(--muted-foreground), centered.
- Bottom usage bar: sticky footer, var(--surface) background, top border 1px solid var(--border), padding 16px 24px; left side "Usage" label 13px var(--muted-foreground) + inline numeric pills (--radius-full, var(--muted) background, var(--foreground) bold number + regular label) for AI tokens and subtitles remaining; right side the split CTA button — primary solid button (var(--primary) bg, var(--primary-foreground) text, --radius-md, height 44px) with the main label bold 14px and the subtext ("English & target language") at 12px reduced opacity (0.85) directly beneath it inside the same button, plus the chevron segment described above. Disabled state (0 selected) = var(--muted) background, var(--muted-foreground) text, no shadow.

5. DARK MODE
Wire up `data-theme` toggling on `<html>` via a `useTheme` hook, persisted to localStorage, defaulting to `prefers-color-scheme`. Add a Sun/Moon Lucide toggle button next to Settings.

6. ACCESSIBILITY
Maintain WCAG AA contrast in both themes with the values above. Every button/input needs a visible focus ring using var(--ring). Icon-only buttons (trash, minus, theme toggle, chevron) need `aria-label`.

7. SCOPE AND CONSTRAINTS
- Do not add Tailwind or a component library dependency — build these as plain CSS/SCSS classes/modules matching the existing file structure.
- Do not change the queue logic, WebDAV scanning, table sorting logic, or any prop/state names.
- List every file created or modified at the end of your response.
- If any existing markup structure blocks a described style (e.g. the toast isn't currently a portal/fixed element), flag it instead of silently restructuring the component tree.
