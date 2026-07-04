# HealthSave Observatory Web UX Redesign Plan

Date: 2026-07-03
Owner: Codex
Scope: `datahub/apps/web`
Live target: `http://apps.internal:18090`
Remote stack: `apps-vm` / `192.168.33.123`, deploy path `/srv/stacks/health-data-hub`

## Objective

Turn the Observatory web app from a technical monitoring console into a clear, user-facing health dashboard.

The current app has useful primitives: recovery score, weekly brief, findings, privacy chain, metric cards, readiness, export, and source status. The redesign must reorganize those into a clean information hierarchy that answers user questions first and exposes technical proof only when requested.

## Non-Negotiables

- Do not touch frozen iOS ingest routes: `POST /api/apple/batch`, `GET /api/apple/status`, `GET /api/health`.
- Do not change v1 API contracts.
- Keep raw health observations local; do not add external media, analytics, or cloud scripts.
- Keep “Observatory” technical detail available, but move it behind drilldowns or Observatory mode.
- Verify desktop and mobile screenshots before calling the redesign done.
- Keep implementation in the existing Next app unless a specific dependency earns its keep.

## Design Direction

Target feel: **Private Health Observatory**.

The UI should feel calm, legible, and trustworthy: closer to a polished health dashboard than Grafana or an internal diagnostics page.

Reference qualities from the supplied images:

- Clean left navigation with obvious active state.
- Light-first, card-based dashboard surface with enough whitespace.
- Strong metric cards with visual charts, not raw text lists.
- Clear filters and page-level controls.
- One primary story per page.
- Technical proof is available but not the first visual layer.

Avoid:

- Infinite dark lists as primary experience.
- Raw metric IDs, p-values, JSON-like calculation fields on first view.
- Tiny mono labels as the main reading layer.
- Repeated equal-weight cards with no obvious priority.
- Decorative gradients that do not serve structure.

## Definition Of Done

- `datahub/apps/web/DESIGN.md` exists and defines reusable tokens, component rules, page hierarchy, and “do/don’t” constraints.
- `Today` gives a clear answer to “How am I doing?” within the first viewport.
- `Findings` prioritizes actionable insights and hides raw calculations by default.
- `Data` works as a clean metric catalog, not a raw readiness dump.
- `Essentials` mode is genuinely user-facing; `Observatory` mode carries the technical layer.
- Mobile layout has no horizontal overflow and no unreadably dense panels.
- `bun run typecheck`, `bun run build`, and available web tests pass.
- Before/after screenshots are saved in a release/audit artifact folder.
- Deployed stack on `apps.internal:18090` serves the redesign.

## Execution Plan

### 1. Baseline Evidence

- [ ] Capture current desktop screenshots:
  - [ ] `/`
  - [ ] `/findings`
  - [ ] `/data`
  - [ ] `/privacy`
  - [ ] `/integrations`
- [ ] Capture current mobile screenshots:
  - [ ] `/`
  - [ ] `/findings`
  - [ ] `/data`
- [ ] Save screenshots under `datahub/apps/web/Plans/artifacts/2026-07-03-observatory-redesign/before/`.
- [ ] Record live state:
  - [ ] `curl -fsS http://apps.internal:18090`
  - [ ] `curl -fsS http://apps.internal:18080/health`
  - [ ] `curl -fsS http://apps.internal:18080/ready`
  - [ ] remote `current-release.env` commit and ports.

### 2. Current UI Audit

- [ ] Map app routes and user jobs:
  - [ ] `Today`: current state and next action.
  - [ ] `Findings`: interpreted changes and evidence.
  - [ ] `Library`: available metrics and pinned signals.
  - [ ] `Integrations`: sync/source setup.
  - [ ] `Privacy`: egress and local trust.
  - [ ] `Settings` / `Intelligence`: technical configuration.
- [ ] Audit each page for:
  - [ ] first visual priority,
  - [ ] page question answered,
  - [ ] primary action,
  - [ ] secondary proof,
  - [ ] empty state,
  - [ ] mobile behavior,
  - [ ] accessibility risks.
- [ ] Write findings to `datahub/apps/web/Plans/artifacts/2026-07-03-observatory-redesign/audit.md`.

### 3. Freeze Design System

- [ ] Create `datahub/apps/web/DESIGN.md`.
- [ ] Define the product identity:
  - [ ] light-first private health dashboard,
  - [ ] dark mode as secondary, not default technical cockpit,
  - [ ] calm health accent and limited semantic chart colors,
  - [ ] clear typography scale,
  - [ ] card, table, filter, chart, empty-state, and drilldown rules.
- [ ] Define mode behavior:
  - [ ] `Essentials`: user-facing summaries, plain language, minimal technical metadata.
  - [ ] `Observatory`: raw evidence, calculations, readiness gates, metric IDs.
- [ ] Define banned patterns:
  - [ ] no generic AI purple gradients,
  - [ ] no raw findings wall on first screen,
  - [ ] no tiny mono as primary body text,
  - [ ] no unlabeled icon-only controls,
  - [ ] no decorative charts without labels.

### 4. Information Architecture Pass

- [ ] Rename or reframe navigation around user jobs:
  - [ ] `Today`
  - [ ] `Trends` or `Findings`
  - [ ] `Data`
  - [ ] `Sources`
  - [ ] `Privacy`
  - [ ] `Settings`
- [ ] Decide which existing routes stay URL-accessible but move out of default navigation.
- [ ] Reduce first-level navigation noise in Essentials mode.
- [ ] Add page headers that answer “what am I looking at?” in plain language.

### 5. Shell Redesign

- [ ] Redesign `Shell`, `Sidebar`, `Topbar`, and status pills.
- [ ] Implement light-first theme tokens in `globals.css`.
- [ ] Keep dark mode but tune it after light mode works.
- [ ] Make the sidebar calm and readable:
  - [ ] grouped nav,
  - [ ] obvious active state,
  - [ ] sync status at bottom,
  - [ ] clear Essentials/Observatory toggle.
- [ ] Add responsive mobile navigation that is usable with one hand.

### 6. Today Page Redesign

- [ ] Recompose the first viewport:
  - [ ] primary recovery/readiness state,
  - [ ] one human summary,
  - [ ] last sync freshness,
  - [ ] top 1-3 “needs attention” items.
- [ ] Replace long evidence-first layout with compact sections:
  - [ ] Recovery,
  - [ ] Sleep,
  - [ ] Heart,
  - [ ] Activity,
  - [ ] Sync status.
- [ ] Move proof/calculation detail behind disclosure or Observatory mode.
- [ ] Redesign empty state as a setup path:
  - [ ] connect app,
  - [ ] sync data,
  - [ ] wait for baseline.

### 7. Findings Page Redesign

- [ ] Split findings into groups:
  - [ ] Needs attention,
  - [ ] Improving,
  - [ ] Watching,
  - [ ] Background evidence.
- [ ] Show 3-5 most important findings first.
- [ ] Convert engine language into user language.
- [ ] Keep `show calculation` available but collapsed and visually secondary.
- [ ] Add severity/action labels that do not rely on color alone.

### 8. Data Page Redesign

- [ ] Make Data a metric catalog:
  - [ ] category groups,
  - [ ] clear filters,
  - [ ] metric cards with readable chart previews,
  - [ ] readiness as status, not the main content.
- [ ] Keep export as a clear secondary action.
- [ ] Move raw readiness rows lower or into Observatory mode.
- [ ] Improve no-data and waiting-for-baseline states.

### 9. Sources, Privacy, Integrations

- [ ] Ensure `Sources` answers “is my data arriving and from where?”
- [ ] Ensure `Privacy` answers “where did my data go?”
- [ ] Ensure `Integrations` answers “what can I connect next?”
- [ ] Use the same card, status, empty, and action patterns from the core pages.

### 10. Component System Pass

- [ ] Extract shared primitives only where they reduce real duplication:
  - [ ] `PageHeader`
  - [ ] `StatusBadge`
  - [ ] `MetricTile`
  - [ ] `InsightCard`
  - [ ] `Section`
  - [ ] `EmptyState`
  - [ ] `Disclosure`
- [ ] Keep component API small and aligned with existing server-component data flow.
- [ ] Avoid adding a full UI library unless existing bespoke components become a blocker.

### 11. Accessibility And Interaction

- [ ] Check text contrast in light and dark modes.
- [ ] Ensure all icon-only buttons have accessible labels.
- [ ] Ensure focus states are visible.
- [ ] Ensure touch targets are at least 44px where practical.
- [ ] Preserve `prefers-reduced-motion`.
- [ ] Make keyboard navigation coherent for nav, filters, disclosures, and export controls.

### 12. Verification

- [ ] Run:
  - [ ] `bun run typecheck`
  - [ ] `bun run build`
  - [ ] `bun test app/`
- [ ] Capture after screenshots:
  - [ ] desktop `/`, `/findings`, `/data`, `/privacy`, `/integrations`
  - [ ] mobile `/`, `/findings`, `/data`
- [ ] Compare against before screenshots and record changes in:
  - [ ] `datahub/apps/web/Plans/artifacts/2026-07-03-observatory-redesign/verification.md`
- [ ] Verify no horizontal scroll on mobile.
- [ ] Verify no console errors in browser capture.

### 13. Deploy

- [ ] Commit the web redesign changes in `datahub`.
- [ ] Push `main` to `umutkeltek/healthsave-observatory`.
- [ ] Deploy to `apps-vm` using the repo’s remote VM deploy path.
- [ ] Verify live:
  - [ ] `http://apps.internal:18090`
  - [ ] `http://apps.internal:18080/health`
  - [ ] `http://apps.internal:18080/ready`
  - [ ] `http://apps.internal:3300/api/health`
- [ ] Check remote containers:
  - [ ] `web`
  - [ ] `api`
  - [ ] `worker`
  - [ ] `homeassistant-mqtt`
  - [ ] `grafana`
- [ ] Record deployed commit in the verification artifact.

### 14. Final Closeout

- [ ] Final response includes:
  - [ ] deployed commit,
  - [ ] live URL,
  - [ ] test/build results,
  - [ ] screenshot artifact paths,
  - [ ] any known residual risks.
- [ ] Update HealthSave memory with durable result:
  - [ ] what changed,
  - [ ] deployed commit,
  - [ ] verification evidence,
  - [ ] next obvious improvement.

## Risk Register

- **Risk:** redesign accidentally hides technical trust evidence.
  - **Mitigation:** keep Observatory mode and drilldowns; only demote proof from first layer.
- **Risk:** light-first theme makes PHI feel too consumer/social.
  - **Mitigation:** restrained palette, no gamification, no social sharing language.
- **Risk:** CSS rewrite causes regressions across many routes.
  - **Mitigation:** shell + tokens first, then page-by-page screenshots.
- **Risk:** dashboard becomes pretty but less useful.
  - **Mitigation:** each page must answer one user question before adding visuals.
- **Risk:** API/backend contract drift.
  - **Mitigation:** no v1 or ingest changes; read-only UI changes unless a v2 additive endpoint is explicitly needed.

## First Implementation Slice

Start with the smallest slice that proves the direction:

1. Add `DESIGN.md`.
2. Redesign shell tokens/sidebar/topbar.
3. Redesign only `Today`.
4. Capture before/after desktop and mobile.
5. If the direction works, continue to `Findings` and `Data`.

Do not redesign every route in one uncontrolled pass.
