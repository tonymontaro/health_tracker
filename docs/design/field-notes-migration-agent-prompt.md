# Field Notes migration agent prompt

Use this document as the complete task prompt for the AI agent that will migrate Health Autopilot to the Field Notes design.

Design system: [`field-notes-design-system.md`](field-notes-design-system.md).

Visual prototype: [`design-explorations/field-notes/index.html`](../../design-explorations/field-notes/index.html).

## Prompt begins

You are responsible for migrating the current Health Autopilot application to the Field Notes design language.
The branch you receive at migration time is the only authoritative source for the application’s current features and behavior.
Do not use a feature list from an older branch, prior design note, conversation summary, or static prototype as a substitute for auditing the current branch.

The goal is a high-quality visual and interaction migration that preserves all current capabilities while establishing a consistent component system for future work.
The static Field Notes prototype is the visual reference, and the Field Notes design-system document is the production design specification.
The repository’s current code, schemas, tests, routes, API contracts, architecture documentation, and active agent instructions are the functional specification.

### Core operating rules

1. Preserve every feature and behavior discovered on the target branch unless the user explicitly approves a change.
2. Do not remove, merge, hide, or weaken a feature because it does not fit the prototype neatly.
3. Do not invent data, metrics, states, narratives, routes, or behaviors to make production resemble mock content.
4. Do not treat the prototype’s mock readiness score, mock route, mock timer, sample coach name, sample meals, sample navigation, or sample history as production requirements.
5. Do not change backend behavior, API contracts, persistence, validation, authentication, authorization, security, privacy, route semantics, query invalidation, or domain rules as part of a visual migration.
6. Treat new components as planned work that must appear in the proposed component registry before implementation.
7. Treat new product logic, derived data, API fields, endpoints, database changes, routes, persistence, dependencies, or workflows as separate proposals that require explicit approval before implementation.
8. Treat feature removal or changed behavior as a separate proposal that requires explicit approval before implementation.
9. Preserve unrelated user changes and never reset or discard the worktree.
10. Keep changes focused, reviewable, accessible, responsive, typed, tested, and consistent with the current repository architecture.

### Required references

Before planning or editing, read all of the following completely:

- Every applicable `AGENTS.md` file and repository instruction file.
- The current `README.md`.
- The current architecture and behavior documentation.
- [`field-notes-design-system.md`](field-notes-design-system.md).
- The Field Notes prototype HTML, CSS, and JavaScript.
- The current application router and layout or shell.
- Every current user-facing page and shared UI component.
- The current API client and frontend data types.
- The current backend route declarations and response schemas used by the UI.
- Current tests covering user-visible behavior.
- Current package scripts and quality gates.

Read referenced files deeply enough to understand behavior rather than only collecting filenames.
Do not begin implementation while any relevant instruction file is unread or any primary feature surface remains uninspected.

### Authority model

This prompt authorizes read-only discovery and creation of a migration plan.
It does not authorize implementation before the first approval checkpoint.

After the user approves the complete preservation ledger, target component registry, and phased migration plan, you may implement the approved presentational work.
That approval covers only the components and view-level interaction adaptations described in the plan.

Stop and request additional approval whenever later work reveals any of the following:

- A new component that was not included in the approved component registry.
- New application or domain logic.
- A new derived value, score, trend, or claim.
- A new API request, field, endpoint, or payload shape.
- A change to persistence, ownership, source, provenance, validation, or audit behavior.
- A new route, redirect, query-parameter meaning, or navigation behavior.
- A new dependency, build tool, test framework, analytics event, or feature-flag mechanism.
- A feature removal, merge, replacement, or loss of discoverability.
- A change to security, authentication, authorization, CSRF, secrets, privacy, or provider behavior.
- A change that affects backend data flow or domain invariants.
- A visual deviation from the Field Notes system that would create a second design language.

Do not implement the unapproved item while continuing with adjacent work if doing so would make later removal difficult or create an incomplete user flow.
Safe, independent work already covered by the approved plan may continue only when the proposed change is truly isolated.

## Phase A: establish the migration baseline

Perform this phase without changing production code.

### A1. Confirm the target source state

- Run `git status --short` and record that unrelated changes must be preserved.
- Record the current branch name and commit hash in the migration plan.
- Do not fetch, pull, switch branches, merge, rebase, or install dependencies unless the user separately authorizes it.
- Treat the checked-out branch contents as the source to audit.

### A2. Build a route and entry-point inventory

Inspect the active frontend router, redirects, nested layouts, deep links, query parameters, external links, authentication boundaries, extension surfaces, and any other user entry points.

Record for every entry point:

- Current path or invocation.
- Parent layout or shell.
- Authentication and authorization requirement.
- Query-parameter and redirect behavior.
- Loading, empty, error, unauthorized, and not-found behavior.
- Desktop and mobile navigation path.
- Existing tests.

Do not assume that routes shown in the Field Notes prototype are complete.

### A3. Build the feature-preservation ledger

Inspect every page, dialog, drawer, form, disclosure, menu, action, mutation, provider integration, and visible read-only detail.
Trace user-facing behavior through frontend handlers, API calls, backend routes, schemas, persistence, and tests when necessary.

Create `docs/design/field-notes-feature-preservation-ledger.md` on the migration branch using this schema:

| ID | Entry point | Capability | User action or visible output | Read dependencies | Write behavior | States and constraints | Current tests | Field Notes target | Planned component | Verification | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

Use stable IDs such as `AUTH-001`, `TODAY-001`, `HISTORY-001`, or names derived from the current domain.
The exact prefixes must come from the discovered application rather than this prompt.

Each row must represent one independently verifiable capability.
Do not combine multiple mutations or materially different states into a single vague row such as “settings work” or “history is preserved.”

For each capability, record at least:

- What the user can see or do.
- Which data and API behavior it depends on.
- Whether it reads, writes, redirects, copies, downloads, opens an external destination, or starts a provider flow.
- Every meaningful status, disabled state, lock, historical restriction, validation failure, empty state, and provider state.
- Any visible source, confidence, provenance, audit, warning, safety, or privacy information.
- The target Field Notes location and interaction pattern.
- The exact verification that proves preservation.

Include capabilities exposed only under unusual data or error conditions.
Search tests, schemas, backend guards, status enums, conditional rendering, and error branches to discover those conditions.

### A4. Build an API and behavior parity ledger

Create a second table in the same ledger document:

| UI capability ID | Current request | Method | Parameters or payload | Success effect | Cache invalidation or refresh | Failure behavior | Planned change |
| --- | --- | --- | --- | --- | --- | --- | --- |

Every current browser request and externally visible navigation should appear in this table.
The default value of “Planned change” for a visual migration is “None.”

If the proposed design appears to need a contract change, do not put that change into the baseline plan.
Create a separate approval request describing the need, options, risks, and a no-contract-change alternative.

### A5. Build the current component and style inventory

Inventory existing shared components, page-local components, status renderers, forms, buttons, feedback, overlays, navigation, loading states, empty states, error states, CSS tokens, global selectors, breakpoints, and responsive behavior.

Record:

- Which components own behavior or API calls.
- Which components are purely presentational.
- Which patterns are duplicated.
- Which selectors have global side effects.
- Which current components can be restyled safely.
- Which components require an adapter or replacement.
- Which legacy styles cannot be removed until all consumers migrate.

### A6. Capture a behavioral and visual baseline

Run the current project’s documented checks before editing.
If an existing check fails, investigate it and record the result rather than assuming the migration caused it later.

Capture representative screenshots or browser recordings for every route and high-risk state that can be reached safely.
Use mock interception, fixtures, seeded data, or existing test helpers when the repository provides them.
Do not expose secrets or mutate real user data merely to obtain a screenshot.

At minimum, capture:

- Wide desktop.
- Narrow desktop or tablet.
- A mobile viewport close to 390 by 844.
- The minimum supported width.
- One loading state.
- One empty state where applicable.
- One error state where safely reproducible.
- Every major overlay or multi-step interaction.
- Every state that changes which actions are available.

### A7. Audit the branch for change during migration

Because the application may continue to receive features, record the audit commit hash in the preservation ledger.
Before each implementation phase, compare the current working tree and commit with that audit point.

If relevant application files have changed:

1. Re-run route, API, component, schema, and status discovery for the changed area.
2. Add new capabilities and states to the preservation ledger.
3. Update the target component registry and tests.
4. Present any new component or logic requirements for approval before implementing them.

Never continue from a stale feature ledger merely because a phase was approved earlier.

## Phase B: design the target system from the live inventory

Perform this phase without changing production code.

### B1. Assign each feature a Field Notes treatment

Use the design system’s foundations, page archetypes, component semantics, responsive rules, and accessibility requirements.
For every feature-ledger row, specify where and how the capability will appear.

The mapping must answer:

- Which page archetype contains it.
- Whether it appears in the default document, a margin annotation, a disclosure, or a detail sheet.
- Which information remains visible before interaction.
- Which action is primary, secondary, destructive, or contextual.
- How status, source, provenance, confidence, validation, and safety remain distinct.
- How the treatment changes on mobile without losing access.
- How loading, empty, error, disabled, locked, completed, historical, and unknown states appear.
- How keyboard and screen-reader users reach and understand it.

Apply this header-content rule while mapping routes:

- Reserve the large Field Notes hero for the primary daily page.
- Preserve its date folio on the left and circular readiness score on the right at desktop sizes when the audited branch provides those values.
- If today's planned exercise is complete and coach feedback exists, place a concise version of that feedback in the center message.
- Before exercise completion, place a brief factual summary of today's planned exercise program and meals in the center message.
- If completed exercise feedback is unavailable, use a concise factual completion summary from existing data and do not invent a coach response.
- Keep the headline short and use no more than two short supporting sentences.
- Give Archive or History, Shopping or Provisions, Settings, and other evidence or utility pages compact functional headers instead of oversized generic statements.
- If this behavior requires data, state, API work, or new product logic that the audited branch does not currently provide, document it in the component registry and approval register, then request approval before implementing it.

Apply this AI-conversation rule while mapping coaching capabilities:

- Use the bottom coaching section of the primary daily page for an ongoing chat with the AI and a readable preview of recent chronological history.
- Provide access to the complete available conversation history and a composer for continuing the thread.
- Preserve the audited branch's true history scope, sender identities, timestamps, persistence, loading, streaming, tool, failure, retry, and safety behavior.
- Clearly distinguish user messages, AI messages, system status, proposed changes, and applied changes.
- Do not reduce an existing conversation to a single editorial note.
- Do not simulate conversation persistence or introduce AI chat behavior if the audited branch does not provide it.
- If a chat surface, persistent history, or any required state and API behavior would be new, plan it in the component registry and approval register and request approval before implementation.

Do not copy the prototype’s content arrangement when the current feature set requires a different structure.
Adapt the Field Notes grammar while preserving all current capabilities.

### B2. Create the target component registry

Create `docs/design/field-notes-component-registry.md` using this schema:

| Component | Semantic purpose | Variants | State model | Accessibility contract | Current consumers to migrate | Logic ownership | New logic required | Verification |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |

Include every proposed shared component and every intentionally page-specific composition.
Mark components as one of the following:

- **Foundation:** token, type, spacing, layout, rule, or focus behavior.
- **Primitive:** button, link, field, status, notice, disclosure, tab, or fact list.
- **Pattern:** masthead, edition header, story, sheet, record flow, review editor, date index, or data list.
- **Composition:** a route-level arrangement of patterns with no reusable semantic contract.

For each component, state whether it is purely presentational, owns local UI state, adapts existing application behavior, or would require new product logic.
Any component with new product logic requires a separate approval item.

Prefer extending a semantic component with a small, explicit variant over creating multiple visual aliases.
Do not build a universal component with dozens of unrelated props.

### B3. Define the target file architecture

Propose a file structure that fits the current repository instead of imposing a generic design-system template.

The proposal should identify:

- Token and foundation styles.
- Shared design-system components.
- Shared interaction hooks only when current patterns justify them.
- Page compositions.
- Tests.
- Temporary legacy styles and their removal point.

Do not introduce a new styling library, component library, state library, icon package, font package, Storybook, visual-test service, or build system without approval.
Prefer the current framework, native platform behavior, CSS custom properties, inline SVG, and existing test tools.

### B4. Define migration slices

Plan incremental vertical slices rather than a big-bang rewrite.
Each slice must end in a runnable, testable application with no feature loss.

A sensible slice sequence usually follows this dependency order:

1. Foundations and shared primitives.
2. Application shell, navigation, global loading and error behavior, and authentication surfaces.
3. One low-risk read-oriented route to validate the design grammar.
4. One representative mutation-heavy route to validate forms, status, feedback, and sheets.
5. Remaining routes grouped by shared component reuse and risk.
6. Rare, locked, historical, provider, and failure states.
7. Responsive, accessibility, and consistency hardening.
8. Legacy-style removal only after the final consumer has migrated.

Derive actual slices from the branch inventory.
Do not use route names or feature groups from the static prototype as the plan.

For every slice, provide:

- Feature-ledger IDs in scope.
- Files expected to change.
- Components introduced or extended.
- Behavior explicitly unchanged.
- Tests to add or update.
- Browser states to verify.
- Approval items, if any.
- Rollback or isolation strategy.

### B5. Create an explicit approval register

List every decision that needs approval in a table:

| Approval ID | Proposed change | Why the visual migration cannot express it with current behavior | Alternatives | Data or user impact | Recommendation | Status |
| --- | --- | --- | --- | --- | --- | --- |

Include feature removals even when you recommend against them.
Include new logic, new components not already covered by the registry, contract changes, dependencies, and route changes.

If the visual migration can preserve the feature with a less elegant composition, present that no-behavior-change option.
Do not frame implementation cost as the main argument.
Prefer correctness, clarity, accessibility, robustness, and maintainability.

## First approval checkpoint

After completing Phases A and B, stop and present the user with:

1. The audited branch and commit hash.
2. A concise audit summary with counts of routes, entry points, feature-ledger rows, browser requests, current components, statuses, and high-risk flows.
3. Links to the complete feature-preservation ledger and component registry.
4. The proposed target information architecture.
5. The phased migration plan.
6. The approval register.
7. Baseline verification results and any pre-existing failures.
8. A clear statement that production code has not yet been changed.

Ask the user to approve the plan before implementation.
Do not begin Phase C in the same turn unless the user has already explicitly approved this exact ledger, registry, phase plan, and approval register.

## Phase C: implement approved foundations

Begin only after the first approval checkpoint is satisfied.

### C1. Protect behavior

- Keep existing data-fetching and mutation behavior in place.
- Move behavior only when the approved plan requires it and tests prove parity.
- Prefer passing data, state, and callbacks into new presentation components.
- Do not duplicate requests or create parallel sources of truth.
- Keep current cache keys, invalidation, error propagation, and loading semantics unless explicitly approved.
- Keep current authentication and security dependencies unchanged.

### C2. Introduce tokens first

- Add semantic Field Notes tokens for color, type, spacing, rules, focus, layering, and motion.
- Apply the foundation to one controlled surface before changing every route.
- Add reduced-motion behavior and accessible focus styles at the foundation stage.
- Avoid broad selectors that unexpectedly restyle third-party, extension, or future elements.
- Do not delete legacy variables until no remaining consumer needs them.

### C3. Implement approved primitives

Build the approved primitive components and their complete state matrices before composing full pages.

For each primitive:

- Use semantic HTML.
- Preserve ref forwarding or focus requirements where overlays and forms need it.
- Add typed props that reflect semantic choices rather than arbitrary visual knobs.
- Cover default, hover, focus, active, disabled, loading, success, warning, error, and unknown states where applicable.
- Test keyboard behavior and accessible naming.
- Use centralized status and provenance mapping created from the live branch inventory.

### C4. Implement approved patterns

Build patterns from primitives and keep domain behavior outside purely visual layers.

- The masthead must accommodate the full discovered navigation rather than only the prototype labels.
- Edition headers must omit unsupported metrics rather than fabricate content.
- Sheets must manage focus, Escape, scroll lock, and focus return.
- Record and review patterns must preserve every discovered step and validation state.
- Form patterns must preserve values, help text, server errors, and pending state.
- Notices must provide correct live-region behavior.

Run focused tests after every primitive or pattern group.

## Phase D: migrate approved vertical slices

For each approved slice, follow this exact loop.

### D1. Re-audit the slice

Compare the target files against the audit commit and inspect any relevant changes added since approval.
Update the preservation ledger before editing.
Request approval for any newly required component or logic.

### D2. Write or update regression coverage

Add focused tests for the existing behavior before restructuring it when coverage is absent and the current test architecture supports it.
Do not introduce a new test dependency without approval.

At minimum, cover:

- Data rendering.
- User actions and submitted payloads.
- Loading, empty, failure, disabled, locked, and success states.
- Conditional behavior driven by date, status, source, permissions, or provider state.
- Navigation and query-parameter preservation.
- Focus and keyboard behavior for new overlays or tabs.

### D3. Migrate the composition

- Replace visual structure while preserving the existing functional container, hooks, requests, and callbacks wherever practical.
- Use shared Field Notes components from the approved registry.
- Keep each action beside the information needed to understand its consequence.
- Use progressive disclosure for depth, not for hiding important state or safety information.
- Preserve all source, provenance, confidence, assumption, historical, and audit details discovered in the ledger.
- Preserve exact constraints and validation behavior.
- Avoid adding browser-side interpretation of health data to generate editorial copy.

### D4. Verify the slice

- Run focused unit and integration tests.
- Run lint and type checks for the affected workspace.
- Build the affected application.
- Exercise every ledger row in the slice in a browser.
- Test wide desktop, narrow desktop or tablet, 390-pixel mobile, and the minimum supported width.
- Test keyboard-only navigation, focus visibility, overlay focus return, reduced motion, and 200 percent zoom.
- Check console errors, failed requests, overflow, content clipping, and layout shift.
- Compare requests, payloads, mutations, redirects, and cache updates with the baseline.
- Update the ledger row to verified only when the behavior and visual treatment both pass.

### D5. Report the slice

After each slice, report:

- Feature-ledger IDs completed.
- Components added or changed.
- Tests and checks run.
- Any behavior intentionally unchanged but visually relocated.
- Any unresolved state, regression, or design inconsistency.
- Any new approval request.

Do not call the slice complete while a ledger row is missing, partially migrated, or unverified.

## Phase E: consistency and completeness audit

After all approved slices are implemented, perform an independent full-application audit against the then-current branch.

### E1. Rebuild the inventory from source

Repeat route, component, request, schema, status, and conditional-rendering searches from scratch.
Compare the fresh result with the preservation ledger.

Any newly discovered or newly added feature must be entered, planned, approved when required, migrated, and verified before completion.

### E2. Audit component consistency

Search for duplicate or one-off implementations of:

- Buttons and text actions.
- Status and provenance.
- Forms and validation.
- Dialogs, drawers, disclosures, and tabs.
- Loading, empty, error, warning, lock, and success feedback.
- Page headers and navigation.
- Metrics and definition lists.
- Breakpoints, spacing, color, focus, and motion values.

Replace accidental duplication with approved shared components.
Do not force semantically different behavior into one component merely to reduce file count.

### E3. Audit design fidelity

Compare every route with the design system and the Field Notes prototype’s visual character.

Verify that:

- The interface feels like one publication.
- Each page has one clear title and hierarchy.
- Rules and typography organize content more often than generic cards.
- Color remains restrained and semantic.
- Long forms use compact editorial structure.
- High-density evidence remains readable.
- Mobile keeps the same capabilities.
- Mock prototype data or unsupported claims have not entered production.

### E4. Audit behavior parity

Require every preservation-ledger row to have one of these final states:

- `Verified unchanged`.
- `Verified with approved change`, with the approval ID recorded.
- `Blocked`, with a user-approved deferral.

No row may remain `Planned`, `In progress`, `Unknown`, or blank at final handoff.

Compare the final API and behavior ledger with the baseline.
Every difference must link to an approval ID.

### E5. Remove legacy styles safely

Remove a legacy component or selector only after repository search proves that no active consumer remains.
Run the full verification suite after removal.

Do not manually modify generated files or changelogs.
Update developer documentation only when the migration changes the supported workflow or architecture.

## Required final verification

Run the repository’s documented full quality gates.
At minimum, include the affected workspace’s lint, typecheck, tests, and production build.
Run broader verification when the migration crosses workspaces or affects shared behavior.

The final browser matrix must cover every route and every high-risk state in the preservation ledger.
Automated checks should fail on console errors, unhandled page errors, failed required requests, missing assets, unexpected horizontal overflow, inaccessible dialogs, and broken navigation.

Perform a manual visual review at each supported layout class.
Automated screenshots do not replace reading the page, inspecting hierarchy, checking truncation, and using the flows.

## Definition of done

The migration is complete only when all of the following are true:

- The fresh final audit matches the preservation ledger.
- Every ledger row is verified or has an explicitly approved deferral.
- Every behavior difference links to explicit approval.
- Every approved shared component exists, is used consistently, and satisfies its accessibility contract.
- No unapproved new logic, data, route, dependency, persistence, or feature removal was introduced.
- Every current route and deep link remains functional unless an approved route change says otherwise.
- Every current read, write, provider, clipboard, redirect, correction, review, and disclosure capability remains reachable.
- Loading, empty, error, disabled, locked, historical, success, unknown, and provider states are represented wherever the current application supports them.
- Desktop, tablet, mobile, keyboard, zoom, reduced-motion, and screen-reader-critical interactions pass.
- Lint, typecheck, relevant tests, and production builds pass.
- The worktree contains no unrelated changes created by the migration.
- The final interface follows the Field Notes design system without becoming a themed copy of the old card layout.

## Required final handoff

Lead with the migration outcome.
Then provide:

1. Routes and capability groups migrated.
2. Shared components and foundations introduced.
3. Links to the final preservation ledger and component registry.
4. Approved behavior changes, if any, with approval IDs.
5. Tests and browser matrices completed.
6. Remaining risks or explicitly approved deferrals.
7. Relevant file links for review.

Do not claim full feature preservation without citing the completed preservation ledger and final source audit.

## Prompt ends
