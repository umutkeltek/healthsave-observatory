# HealthSave Observatory Web Design System

## Direction

HealthSave Observatory is a private health-data dashboard for people who want to understand and control their own health data. The web UI should feel calm, legible, trustworthy, and local-first.

Design posture: **macOS-inspired Private Health Observatory**.

Use Apple-like grouped surfaces, subtle materials, system typography, compact spacing, and clear hierarchy. This is not literal macOS cosplay: do not add fake traffic lights, desktop wallpaper, or theatrical chrome unless the product is actually showing a window metaphor. Linear is a useful reference for density and token discipline, not for the dark neon visual identity.

## One language (non-negotiable)

There is exactly ONE design language: macOS-light-first (Apple system). Dark is a
single supported override, not a second identity. Enforcement:

- All colour comes from CSS custom properties (tokens). Light values live once in
  `:root`; dark deltas live once in `[data-theme="dark"]`. No third palette layer,
  no periwinkle / indigo / mint remnants.
- No hardcoded hex/rgba in component CSS or JSX when a token exists. Sleep, baseline,
  chart, and semantic colours all have tokens — use them.
- Do not add "polish / alignment / reset" override passes that re-skin
  `.hero` / `.card` / `.topbar` / `.sidebar`. Fix the single definition instead.
  A duplicate top-level selector is a bug, not a layer.

## Color

Light mode is the primary experience.

- Canvas / grouped background: `#F2F2F7`
- Elevated surface: `#FFFFFF`
- Tertiary surface: `#E5E5EA`
- Primary text: `#1D1D1F`
- Muted text: `#6E6E73`
- Divider: `rgba(60, 60, 67, 0.18)`
- Hover: `rgba(0, 0, 0, 0.04)`
- Pressed: `rgba(0, 0, 0, 0.08)`
- Sidebar material: `rgba(246, 246, 246, 0.72)`
- System blue: `#007AFF`
- Health green: `#30D158`
- Attention orange: `#FF9F0A`
- Risk red: `#FF453A`
- Sleep purple: `#AF52DE`

Dark mode uses the same hierarchy with macOS dark surfaces:

- Canvas: `#000000`
- Secondary: `#1C1C1E`
- Elevated: `#2C2C2E`
- Tertiary: `#3A3A3C`
- Primary text: `#F5F5F7`
- Muted text: `#98989D`
- Divider: `rgba(84, 84, 88, 0.65)`
- System blue: `#0A84FF`

Use health colors only for semantic status and charts. System blue is the primary UI accent for navigation, links, primary actions, and focus.

## Typography

Use the Apple system font stack everywhere:

```css
-apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", "Segoe UI", sans-serif
```

Do not use Roboto, Open Sans, Material fonts, or decorative display fonts.

- Large display text over 34px: weight `600-700`, letter-spacing `-0.02em` to `-0.03em`.
- Body text 13-17px: weight `400`, letter-spacing `0`.
- Small labels 10-12px: weight `500-600`, letter-spacing `0.01em` to `0.02em`.
- Use tabular figures for health metrics, counts, and timestamps.

## Spacing And Shape

Use the 8pt spacing scale:

`4, 8, 12, 16, 20, 24, 32, 40, 48, 64, 80`

- `4px` is reserved for tight in-component spacing.
- Content margins are at least `16px`; regular dashboard pages use `20-24px`; hero surfaces can use `32px`.
- Form rows use `12px` between fields and `8px` from label to input.
- Cards use `16px` compact padding, `20-24px` regular padding, and `32px` for hero surfaces.

Radius scale:

- Buttons: `8px`
- Chips and segmented controls: `6-8px`
- Cards and tiles: `12-16px`
- Sheets and modals: `16-20px`
- Full pills: `999px`

## Layout

- Shell: vibrancy-style left sidebar, content pane on grouped background.
- Toolbar: unified top app bar around `52px` visual height with page title, status, and utility controls.
- First viewport should answer one user question before showing proof.
- Raw evidence, p-values, readiness gates, calculation fields, and metric IDs belong behind drilldowns or Observatory mode.
- No horizontal overflow on mobile-width layouts.

## Navigation

Essentials mode is normal use:

- Today: how am I doing?
- Findings: what changed?
- Data: what do I have?
- Sources: is sync healthy?
- Privacy: where did my data go?
- Settings: what can I configure?

Observatory mode can expose deeper surfaces: compare, relationships, experiments, intelligence, raw readiness, and calculation detail.

Sidebar rules:

- Use material background with `backdrop-filter: blur(40px) saturate(180%)`.
- Active row must be obvious.
- Row icons should be 16px, thin stroke, SF Symbols-like.
- Keep section labels sparse; do not add tiny uppercase labels to every section.

## Components

- Primary button: system blue, white text, `8px` radius, at least `44px` hit area.
- Secondary button: subtle gray/material fill, muted text, `8px` radius.
- Icon button: 28px visual control inside a 44px hit area.
- Segmented controls: 28-32px high, `6-8px` radius.
- Cards should communicate real hierarchy; do not wrap every section in same-weight cards.
- Calculations and raw proof should default collapsed.

## Motion

- Hover/press feedback: about `120ms`.
- Standard fade: about `180ms`.
- Sheet/open transition: about `280ms`.
- Anything above `400ms` needs a product reason.
- Animate transform and opacity, not layout dimensions.
- Respect `prefers-reduced-motion`.

## Do Not Do

- Do not lead with a long raw findings wall.
- Do not make tiny mono labels the main reading layer.
- Do not expose raw calculation JSON in the first layer.
- Do not use generic AI purple/blue gradient decoration.
- Do not use pure white cards on a pure white page; keep the grouped background layer.
- Do not use heavy shadows, Material easing, or Material typography.
- Do not add external tracking, hosted media, or cloud scripts to improve the look.
- Do not change frozen ingest/API contracts to make UI work.
