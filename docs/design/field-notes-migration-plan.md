# Field Notes migration plan

## Approval checkpoint

- Audited branch: `main`.
- Audit commit: `a605fa91be621c668d00bec8eab9261a56d49d9f`.
- Initial worktree: clean.
- Inventory: 17 entry points, 7 rendered web routes, 3 explicit redirect routes plus the wildcard fallback, 55 capability rows, 40 browser request patterns, 23 current React components, and 15 explicit application statuses.
- Target registry: 34 approved foundations, primitives, patterns, and route compositions.
- Baseline: `make verify` passes, including 59 backend tests and both production builds.
- Visual baseline: 15 private screenshots at 1440, 820, 390, and 320 px, including safe loading, empty, disclosure, and route-error states.
- Production code changed at this approval checkpoint: no.

The detailed approval artifacts are [the preservation ledger](field-notes-feature-preservation-ledger.md) and [the component registry](field-notes-component-registry.md).

## Implementation result

- Completed after explicit approval on 15 August 2026.
- Exercise is the default homepage and first navigation destination across the web app, extension, and email links.
- The homepage uses real plan data and includes run, bike, strength, bodyweight, recovery, rest, and mixed-session graphics without route data or fabricated metrics.
- No database migration, API contract, persistence rule, provider behavior, or planner behavior changed.
- No Playwright dependency or end-to-end test suite was added, at the user's direction.
- `make verify` passes with 59 backend tests, all lint and type checks, and both production builds.
- The final manual browser matrix at 1440, 820, 390, and 320 px has one `h1` per route, no unlabeled controls, no undersized audited targets, no positive horizontal overflow, and no captured page errors.

## Target information architecture

| Priority | Destination | Route | Field Notes treatment |
| --- | --- | --- | --- |
| 1 | Exercise | `/today/exercise` | Exercise-first homepage with the daily hero, exercise figure, planned and actual work, recording, next action, and coaching thread |
| 2 | Food | `/today/food` | Daily food edition with meal stories, recipes, fruit, snacks, fallback plate, diary evidence, next action, and coaching thread |
| 3 | History | `/history/exercise`, `/history/nutrition` | Compact Archive page with an Exercise-first subsection and evidence-focused date index |
| 4 | Inventory | `/inventory` | Operational Inventory and Provisions chapters with all current shopping behavior |
| 5 | Settings | `/settings` | Compact configuration, integration, equipment, token, and runtime sections |
| 6 | Study | Existing external URL | Clearly marked external utility link |

Desktop shows all six destinations in the masthead in this order.
Mobile uses Exercise, Food, History, Inventory, and More in the fixed bottom bar, with Settings and Study in the accessible More menu.
The masthead Record action opens links to the existing exercise and food recording sections rather than creating a new recording workflow.

The existing route paths remain intact.
Under APR-001, `/today`, unknown routes, successful login, email links, and the extension's Open full app action will land on `/today/exercise` instead of Food.

## Homepage and exercise graphics

`/today/exercise` becomes the default homepage and follows the static prototype closely in geometry, masthead, date folio, editorial rules, asymmetric lead story, dark coaching section, and responsive bottom navigation.

The mock `82` readiness score is not available in production data and will not be shown.
A real source stamp such as `AI planned` or `Reliable fallback` may occupy that visual anchor, or the stamp will be omitted when it adds no useful context.
The prototype route map will become a privacy-safe schematic that cannot be mistaken for a real route.

`ExerciseFigure` supports every exercise type in the current schema:

| Type | Graphic | Real values allowed |
| --- | --- | --- |
| Run | Abstract interval trace, laps, or effort bands | Distance, pace, treadmill speed, incline, duration |
| Bike | Wheel geometry with a power and cadence profile | Duration, target power range, cadence range |
| Strength | Barbell and plate geometry with set blocks | Load, sets, repetitions, rest |
| Bodyweight | Bodyline geometry with repetition blocks | External load, sets, repetitions, rest |
| Recovery | Quiet movement arcs or duration bands | Duration and instructions |
| Rest | Deliberately sparse rest figure | Summary only; no invented metrics |
| Mixed | Lead figure from the first material exercise plus a textual session sequence | Only metrics present on each real exercise |

All SVG is inline, single-color, responsive, and either labeled as a figure or hidden as decorative.
Text and `FactList` remain the authoritative representation, so the graphic never carries a quantity, status, or safety instruction by itself.

## Implementation slices

Every slice starts by comparing the working tree and commit with the audit point, updating both ledgers for relevant changes, and stopping for approval if a new component, route, contract, dependency, or behavior appears.

### 1. Foundations, shell, and focused states

- Scope: `AUTH-*`, `NAV-*`, and `STATE-001`.
- Files: `styles.css`, new Field Notes style layers, `Layout.tsx`, `App.tsx`, `LoginPage.tsx`, and shared Field Notes primitives.
- Build: tokens, system typography, editorial geometry, actions, fields, status/provenance, notices, loading/error states, masthead, bottom navigation, utility and Record menus.
- Preserve: cookie auth, CSRF, routes, deep links, Study URL, query behavior, and safe API errors.
- Verify: login success/failure, protected redirects, active navigation, keyboard menus, reduced motion, 200 percent zoom, and 1440/820/390/320 layouts.
- Isolation: legacy selectors remain for every page not yet migrated.

### 2. Exercise-first homepage

- Scope: `DATE-001`, `EXER-*`, and the Exercise portion of `CHAT-*`.
- Files: `TodayPage.tsx`, `api/types.ts` only if a type refinement is needed without contract change, `ExerciseFigure.tsx`, Field Notes records/forms/overlays, and page styles.
- Build: data-backed hero, all exercise figures, workout lead, structured completion, regeneration, Strava retrieval, diary analysis/review/submission, actual evidence, next action, and coaching thread.
- Preserve: every current request, payload, cache invalidation, historical restriction, lock, ownership rule, provider source, pain flag, note, measurement, and failure path.
- Verify: run, bike, strength, bodyweight, recovery, rest, mixed, imported, corrected, locked, empty, pending, failure, and historical fixtures.
- Isolation: Food continues on legacy composition until Slice 3.

### 3. Food daily edition

- Scope: `FOOD-*` and the Food portion of `CHAT-*`.
- Files: `TodayPage.tsx`, `MealFigure.tsx`, shared sheets/records, and page styles.
- Build: one/two meal stories, recipe sheets, fruit, snacks, emergency plate, regeneration, diary recording, extraction evidence, assumptions, match confidence, next action, and coaching thread.
- Preserve: recommendation versus actual distinctions, authoritative diary locks, privacy copy, inventory deltas, historical window, and provider failure atomicity.
- Verify: one/two meals, empty fruit/snacks, ate-nothing, matched/discarded, assumed portions, locked suggestions, recipe keyboard flow, and current/historical dates.
- Isolation: Today legacy styles are removed only after both Exercise and Food pass.

### 4. History and corrections

- Scope: `HIST-*`.
- Files: `HistoryPage.tsx`, shared date index, record list, detail sheet, correction form, and archive styles.
- Build: compact Archive header, Exercise-first tabs, desktop/mobile date index, evidence lists, provider links, original-plan disclosure, and a labeled correction sheet replacing browser prompts.
- Preserve: exact PATCH payloads and validation, immutable original plans, diary ownership detachment, source/provenance, historical status, and derived-summary recalculation.
- Verify: empty and populated sections, all statuses and sources, Strava and Garmin evidence, locked food-log records, actual-evidence validation, cancel, focus return, and deep links.
- Isolation: the correction sheet calls the existing mutation without introducing a new API or edit model.

### 5. Inventory and Provisions

- Scope: `INV-*` and `SHOP-*`.
- Files: `InventoryPage.tsx`, operational list, confirm dialog, fields, notices, and page styles.
- Build: AI text addition, ruled inventory records, item editing, explicit delete/remove confirmation, retailer shopping chapter, basket facts, prompt copy, and purchase action.
- Preserve: catalog-name immutability, all fields, validation, source/confidence, draft/purchased lock, item indexes, clipboard behavior, purchase idempotency, and atomic inventory updates.
- Verify: loading/empty/error, catalog and standalone items, every location/unit/confidence, clipboard denial, invalid quantity, destructive cancel/confirm, draft/purchased, and repeat purchase.
- Isolation: existing API ownership remains in `InventoryPage`.

### 6. Settings, integrations, extension, and emails

- Scope: `SET-*`, `EXT-*`, and `EMAIL-*`.
- Files: `SettingsPage.tsx`, extension `main.tsx`, both style entries, `backend/app/services/email.py`, and shared configuration patterns.
- Build: compact profile/rules/capacity/equipment sections, Strava state and confirmations, sensitive token output, runtime sheet, a dense Field Notes extension popup, and matching morning/evening email typography and rules.
- Preserve: every profile field, nested payload, immediate equipment mutation, kitchen save behavior, OAuth redirect, sync/disconnect effects, bearer auth, Chrome permissions/storage, and external tab behavior.
- Verify: configured/unconfigured/connected/reauthorization/error provider states, one-time token handling, callback query preservation, extension setup/loading/rest/error, email plain-text/HTML parity and idempotency, and extension lint/typecheck/build.
- Isolation: no backend, manifest-permission, or API contract change.

### 7. Completeness, accessibility, and legacy removal

- Rebuild the route, request, status, source, component, and conditional-render inventories from source.
- Require every preservation row to be `Verified unchanged`, `Verified with approved change`, or an explicitly approved deferral.
- Audit WCAG 2.2 AA contrast, keyboard order, screen-reader names, focus traps/return, 44 px touch targets, 200 percent zoom, reduced motion, forced colors, text spacing, and no horizontal overflow.
- Compare every route and high-risk state with the prototype's character while checking that no mock score, route, claim, timer, or unsupported narrative entered production.
- Remove a legacy selector only after `rg` shows no active consumer.
- Run `make verify` and the final browser matrix after removal.

## Verification plan

The migration keeps backend tests as the contract and uses focused manual browser checks without adding an end-to-end test framework.

- Baseline and final gate: `make verify`.
- Per-slice gate: frontend lint, typecheck, production build, relevant backend tests, and extension checks when affected.
- Request parity: method, path, query, payload, credentials, CSRF/bearer behavior, success effect, cache invalidation, and safe failure message compared with the API ledger.
- Browser matrix: 1440 wide, 820 narrow/tablet, 390 by 844 mobile, and 320 minimum width for every route.
- State matrix: loading, empty, error, pending, disabled, locked, success, historical, unknown status/source, provider failure, one/two meal, all six exercise kinds, mixed, and major sheets/confirmations.
- Accessibility: keyboard-only traversal, visible focus, dialog Escape/trap/return, screen-reader-critical labels and live regions, 200 percent zoom, text-spacing override, reduced motion, and forced colors.
- Runtime quality: fail on console errors, unhandled page errors, failed required requests, missing assets, clipping, unexpected horizontal overflow, or covered mobile controls.
- Privacy: visual fixtures contain no route/location data, secrets, extension tokens, or committed screenshots of personal health records.

## Approval register

| Approval ID | Proposed change | Why the visual migration cannot express it with current behavior | Alternatives | Data or user impact | Recommendation | Status |
| --- | --- | --- | --- | --- | --- | --- |
| APR-001 | Make Exercise first and change `/today`, wildcard, post-login, email, and extension full-app landing targets from Food to `/today/exercise` | The requested Exercise-first homepage otherwise remains secondary despite the new visual hierarchy | Reorder labels only and retain Food landing | Navigation behavior only; no data/API effect; existing Food deep link remains | Approve as explicitly requested | Approved and implemented |
| APR-002 | Add masthead Record launcher with native links to the existing Exercise and Food record sections | The prototype's distinct Record affordance needs a safe production target without combining the two authoritative flows | Omit Record; duplicate both forms in one new drawer | Adds local menu/fragment navigation only; no request or persistence change | Approve the launcher; do not create a combined recording workflow | Approved and implemented |
| APR-003 | Add `@playwright/test` as a frontend dev dependency and checked-in browser regression suite | The current branch has no frontend test harness for navigation, dialogs, keyboard focus, responsive layout, and request parity | Continue with focused manual browser checks only | Development-only dependency and browser installation; no runtime effect | Exclude at the user's direction | Declined |
| APR-004 | Select daily hero copy from existing workout status, coach feedback, workout title/summary, meal names, and source | Matching the specified pre-completion and post-completion hero requires a small presentational state selection | Use a fixed `Exercise` title and omit contextual center copy | No API/persistence effect; no new metric or claim; unknown/partial cases use factual fallback | Approve with fixture coverage and no browser-generated health conclusions | Approved and implemented |

The user approved the component registry, APR-001, APR-002, and APR-004 before implementation began.
APR-003 was subsequently declined and excluded.
