# Field Notes component registry

Audit source: `main` at `a605fa91be621c668d00bec8eab9261a56d49d9f`.

This registry is the approval boundary for the Field Notes migration.
Components not listed here require a new proposal before implementation.

## Registry

| Component | Semantic purpose | Variants | State model | Accessibility contract | Current consumers to migrate | Logic ownership | New logic required | Verification |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Foundation: `FieldNotesTokens` | Semantic color, type, spacing, rule, focus, layer, and motion values | Default only | Light canvas; reduced motion; forced colors | WCAG 2.2 AA contrast; visible 2 px focus; no text below 0.6875rem | All web routes and extension popup | CSS only | No | Token search, contrast audit, reduced-motion and forced-color checks |
| Foundation: `EditorialLayout` | Shared page width, measures, columns, and responsive padding | Hero, compact, single-column | Wide, 721-920, 431-720, 320-430 | DOM order remains logical at every breakpoint; 200 percent zoom has no loss | Layout and every page | CSS only | No | 1440, 820, 390, and 320 px screenshots plus overflow checks |
| Primitive: `ActionButton` | Typed primary, secondary, text, and destructive actions | Primary, secondary, text, destructive, icon | Idle, hover, focus, pending, disabled, success | Native button; 44 px touch target; accessible pending and disabled reason | All page-local buttons | Presentational | No | Keyboard, focus, disabled reason, pending-label checks |
| Primitive: `Field` | Consistent input, select, textarea, checkbox, range, and help/error association | Text, number, date, select, textarea, checkbox, range, sensitive output | Default, focus, disabled, invalid, pending, saved | Visible label; `aria-describedby`; native semantics; error association | Today editors, Inventory, Settings, Login | Presentational | No | Keyboard, screen-reader naming, server and client validation checks |
| Primitive: `FormSection` | Group related controls beneath a real heading | Standard, compact, sensitive | Idle, pending, saved, warning, error | `fieldset` and `legend` where appropriate; stable live region | Settings, record and review flows | Presentational | No | Heading, tab order, validation, 200 percent zoom |
| Primitive: `StatusLabel` | Central typed rendering of lifecycle status | Ordinary, positive, caution, error, locked, historical, unknown | Planned, confirmed, assumed consumed, skipped, matched by food log, discarded by food log, completed, partial, skipped assumed, skipped by workout log, processed, draft, purchased, unknown | Status text always present; color never sole cue; unknown remains visible | Existing `StatusPill`, all status consumers, extension | Presentational mapping | No | One fixture per audited status plus unknown-status fallback |
| Primitive: `ProvenanceLabel` | Keep source separate from lifecycle status | AI planned, fallback, recommended, manual, correction, food diary, workout diary, Strava, Garmin, regenerated, unknown | Available, unavailable, provider error | Readable text with optional icon; external provider link remains named | Today, History, Inventory, Settings, extension | Presentational mapping | No | Source fixture matrix and provider-link checks |
| Primitive: `FactList` | Display measured values without inventing zeroes | Inline, stacked, inverse | Complete, partial, unavailable | Semantic `dl`; units included in labels or values | Meals, exercise, shopping, integrations, history | Presentational | No | Missing-value and unit tests |
| Primitive: `Notice` | Persistent success, information, warning, privacy, lock, empty, and error feedback | Info, success, warning, error, privacy, lock, empty | Static or transient | `role=status` for nonurgent success; `role=alert` for urgent error; no focus theft | All existing feedback and lock notes | Presentational | No | Live-region and safe API-message checks |
| Primitive: `LoadingState` | Preserve page measure while a query or mutation is pending | Page, section, inline | Loading and delayed loading | Reduced motion; meaningful progress text | Protected shell and all queries | Presentational | No | Intercepted loading screenshots and announcement check |
| Primitive: `ErrorState` | Keep the user in context and expose safe failures | Page, section, inline | Error with optional safe retry | Heading and alert semantics; retry is a button | All route and mutation errors | Existing query callbacks remain owners | No | Intercepted failures, retry, and server-message checks |
| Primitive: `SectionTabs` | Navigate peer sections without changing route semantics | Two-tab, compact | Active, focus, disabled | Links for route navigation; `aria-current=page`; keyboard browser behavior | Today and History tabs | Router owns navigation | No | Deep-link, date-query, back-button, and keyboard checks |
| Pattern: `AppMasthead` | Brand, full desktop destinations, record access, utility menu, and active route | Desktop, compact top, mobile bottom bar | Active destination; utility menu open; signed-in | Semantic nav; `aria-current`; Escape/outside-close; no covered content | `Layout` and route shell | Local menu state only | No | Desktop/mobile navigation matrix and focus return |
| Pattern: `RecordLauncher` | Quick access to the existing exercise and food record sections | Menu, mobile sheet | Closed, open | Button with expanded state; links remain normal navigation | App masthead | Local disclosure state only | No | Exercise and food links, Escape, focus return |
| Pattern: `EditionMeta` | Date, locale, source, range, or count line | One to three items | Complete or omitted item | Semantic `time`; mobile DOM order preserves priority | Every web page | Presentational | No | Date and source rendering at each breakpoint |
| Pattern: `EditionHeader` | Hero daily context or compact functional page title | Hero, compact | Planned, completed with feedback, completed without feedback, no optional stamp | One page `h1`; no decorative text in accessibility tree | Today, History, Inventory, Settings, Login | Receives authoritative copy and values | No | Data-backed copy fixtures and heading audit |
| Pattern: `FolioRule` | Separate editorial chapters with semantic headings | Numbered, unnumbered | Default | Real heading adjacent to rule; number is decorative | Today and long operational pages | Presentational | No | Heading-order inspection |
| Pattern: `StorySection` | Lead or supporting plan and record story | Lead, standard, compact, inverse | Loading, planned, complete, locked, historical | Configurable semantic heading level; action region follows context | Exercise, meals, prep, history summaries | Presentational | No | State matrix and heading order |
| Pattern: `DetailSheet` | Show recipes, exercise detail, system detail, and dense forms on demand | Right sheet, mobile full-width, confirmation | Open, closing, unsaved, pending | Native dialog; focus trap; Escape; scroll lock; focus return; named close | Recipe details, runtime details, record review, correction forms | Local overlay state; caller owns mutations | No | Keyboard-only dialog test and scroll/zoom checks |
| Pattern: `ConfirmDialog` | Replace browser confirms for destructive inventory and shopping actions | Remove item, delete inventory, disconnect provider | Open, pending, error | Explicit target and consequence; destructive focus is not automatic | Inventory and Settings | Caller owns existing mutation | No | Cancel/confirm payload parity and focus return |
| Pattern: `DateIndex` | Navigate Today recording dates and History evidence | Select, horizontal index, sticky desktop index | Selected, empty, loading | Current date announced; horizontal controls keyboard reachable | Today and History | Existing query/date state remains owner | No | Query preservation, selected date, mobile overflow checks |
| Pattern: `RecordList` | Render historical or operational evidence with status and provenance | Nutrition, exercise, inventory, shopping | Empty, loading, locked, editable, historical | List or article semantics; action names include target | History, Inventory, Shopping | Existing page containers own actions | No | Every visible field, source, and action verified against ledger |
| Pattern: `ReviewEditor` | Review extracted workout records before authoritative save | Exercise item, empty extraction | Dirty, invalid, source changed, pending, error | Per-field error association; blocking summary; add/delete named | Workout diary extraction review | Existing local validation and mutations remain unchanged | No | Correction, deletion, addition, stale-analysis, and payload parity |
| Pattern: `CoachConversation` | Inline chronological AI conversation and proposal history | Preview, full feed | Loading, empty, sending, failed, proposed, applied, historical | Sender and time per exchange; composer label; status announcement | Today chat | Existing queries and mutations remain in `TodayPage` | No | Chronology, previous history, proposal state, retry/error checks |
| Pattern: `ExerciseFigure` | Data-backed, privacy-safe schematic for the planned workout | Run, bike, strength, bodyweight, recovery, rest, mixed | Complete metrics, partial metrics, no metrics | Figure label and text facts carry all meaning; SVG is hidden when decorative; 3:1 non-text contrast | Exercise lead story and extension summary if space permits | Pure mapping from existing `Exercise` and workout fields | No | Fixture matrix for all six supported kinds; no route-like paths; no fabricated values |
| Pattern: `MealFigure` | Quiet decorative meal illustration matching the prototype grammar | Meal, fruit, fallback | Default | `aria-hidden=true`; all nutrition facts remain textual | Food page stories | Presentational | No | Screen-reader tree and responsive clipping checks |
| Composition: `TodayExerciseComposition` | Exercise-first daily homepage with hero, workout lead, record flows, next action, and chat | Current, historical, rest | All exercise and chat states in the ledger | One `h1`; primary action visible; full mobile feature parity | `/today/exercise` | `TodayPage` retains existing requests and callbacks | No | EXER, CHAT, DATE, and NAV ledger rows |
| Composition: `TodayFoodComposition` | Food daily edition with meals, actual diary, fruit, optional items, fallback, next action, and chat | Current, historical, one meal, two meals | All food and chat states in the ledger | One `h1`; recipe and record actions keyboard reachable | `/today/food` | `TodayPage` retains existing requests and callbacks | No | FOOD, CHAT, DATE, and NAV ledger rows |
| Composition: `HistoryComposition` | Compact archive and evidence page | Exercise, nutrition | Empty, loading, selected day, mutation error | Date index and records preserve logical order | `/history/exercise`, `/history/nutrition` | `HistoryPage` owns selection and patches | No | HIST ledger rows |
| Composition: `InventoryComposition` | Inventory plus weekly shopping operational page | Inventory, Shopping | Loading, empty, draft, purchased, error | Forms and destructive actions fully named | `/inventory` and `/shopping` redirect | `InventoryPage` owns requests and clipboard | No | INV and SHOP ledger rows |
| Composition: `SettingsComposition` | Compact configuration and integration page | Profile, planning, capacity, equipment, integrations | Loading, saved, provider disabled, provider connected, provider error, sensitive token | Form sections; token output is explicitly sensitive; destructive controls named | `/settings` | `SettingsPage` owns requests and redirects | No | SET ledger rows |
| Composition: `LoginComposition` | Focused authenticated entry | Default, error, pending | Idle, submitting, invalid credentials | Autofill-compatible labels; error alert; focus moves to error summary | `/login` | Existing login and CSRF behavior | No | AUTH ledger rows and redirect checks |
| Composition: `ExtensionComposition` | Field Notes treatment for the Chrome popup without reducing density or permissions clarity | Setup, Today | Loading, configured, permission request, API error | Keyboard reachable; token remains masked; no hidden action | Extension popup | Existing storage, permission, bearer fetch, confirm, and tab behavior | No | EXT ledger rows plus extension lint/typecheck/build |
| Composition: `FieldNotesEmail` | Carry the same calm editorial hierarchy into existing morning and evening email entry points | Morning plan, evening check-in, plain text, HTML | One/two meals, rest/active workout, no prep, provider send failure | Semantic headings and lists; readable without CSS or images; complete plain-text alternative | Scheduled morning and evening emails | Existing email renderer and delivery jobs retain ownership | No | EMAIL ledger rows and existing email/idempotency tests |

## Implemented file architecture

```text
frontend/src/
  components/field-notes/
    ConfirmDialog.tsx
  components/exercise/ExerciseFigure.tsx
  components/food/MealFigure.tsx
  styles/field-notes/
    tokens.css
    foundations.css
    components.css
    pages.css
    responsive.css
  pages/TodayPage.tsx
  pages/HistoryPage.tsx
  pages/InventoryPage.tsx
  pages/SettingsPage.tsx
  pages/LoginPage.tsx
  styles.css
extension/src/
  main.tsx
  styles.css
backend/app/services/email.py
```

`styles.css` remains the single frontend style entry point and imports the Field Notes layers in dependency order.
The approved registry roles that did not require independent state or reuse remain page-local semantic compositions rather than becoming one-file-per-row abstractions.
Legacy visual definitions were replaced after an `rg` consumer check.
No font, icon, styling, state, component, or test dependency was added.
