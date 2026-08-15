# Field Notes design system

Status: target specification for an approved visual migration.

Prototype: [`design-explorations/field-notes/index.html`](../../design-explorations/field-notes/index.html).

Migration-agent prompt: [`field-notes-migration-agent-prompt.md`](field-notes-migration-agent-prompt.md).

## 1. Purpose

Field Notes is the target visual and interaction language for Health Autopilot.
It should make a capable planning system feel calm, personal, trustworthy, and deliberate without hiding its operational depth.

This document defines the design rules that every current and future interface must follow.
It does not authorize product-logic changes, backend changes, feature removal, route changes, or new dependencies.
Those changes require a written proposal and explicit user approval before implementation.

## 2. Product promise

The interface should feel like a carefully edited personal health journal rather than a generic wellness dashboard.
The user should see the meaning of the day before seeing its machinery.
Recommendations should read like an intentional plan, actual records should read like evidence, and system details should remain available as annotations.

The experience must preserve five qualities:

1. **Calm:** The page uses generous space, quiet color, and restrained motion.
2. **Clarity:** The next useful action is obvious without making everything else disappear.
3. **Honesty:** Recommendations, actuals, assumptions, provenance, errors, and safety information remain visibly distinct.
4. **Continuity:** Today, History, Shopping, Settings, login, and future features feel like parts of one publication.
5. **Depth on demand:** Recipes, forms, reviews, raw details, and system information open when requested instead of dominating the default page.

## 3. Non-negotiable product constraints

The visual migration must not weaken any domain, data, operational, privacy, accessibility, or security guarantee that exists on the branch being migrated.
This document intentionally does not enumerate those guarantees because the main branch will continue to evolve.

At migration time, the implementing agent must read the active repository instructions, architecture documentation, schemas, routes, user interfaces, tests, and operational documentation before proposing work.
The then-current branch is the functional source of truth.

- Preserve every discoverable feature, state, route, action, data field, source, provenance indicator, validation rule, accessibility behavior, and error path unless the user explicitly approves a change.
- Preserve all security, authentication, authorization, privacy, persistence, and audit behavior.
- Preserve every distinction the product makes between proposed, planned, actual, assumed, imported, corrected, historical, and immutable information.
- Do not introduce a route map from the prototype unless an approved, privacy-reviewed feature backed by real data requires it.
- Do not display the prototype’s mock readiness score of `82` as real data.
- Do not synthesize metrics, trends, scores, claims, or narrative conclusions that are not supported by current application data.
- Do not remove or conceal a feature because it is difficult to fit into the design.
- Plan any proposed removal, explain the user impact and alternative, and request approval before changing it.
- Treat any new product logic, derived state, API contract, persistence behavior, route, dependency, or workflow as a separate proposal that requires approval before implementation.

## 4. Design character

### 4.1 Editorial, not ornamental

The design uses editorial hierarchy to organize real product information.
Large typography, folio numbers, rules, captions, and margin notes must clarify structure rather than decorate an otherwise unchanged card layout.

Use one strong editorial gesture per viewport.
A page may have a large edition title, a lead story, or a focused coach conversation, but it should not make every section oversized or theatrical.

### 4.2 Personal, not anthropomorphic

The voice may be warm and direct, but the system must not pretend to have feelings, certainty, or knowledge it does not possess.
Coach content should use the text returned by the current product and should not be rewritten in the browser to sound more literary.

The prototype name “Ari” is mock content.
Production should retain the product label discovered on the migration branch or use a separately approved name.

### 4.3 Quiet, not vague

Muted color and generous space must not reduce legibility or obscure state.
Small editorial labels are appropriate for section metadata, but actions, health warnings, form labels, status changes, and errors must remain immediately readable.

### 4.4 Structured, not card-based

Prefer page sections divided by rules, columns, changes in measure, and typographic hierarchy.
Reserve bounded surfaces for dialogs, alerts, critical summaries, and truly independent objects.
Do not recreate the current interface by placing every section in a cream Field Notes card.

## 5. Foundations

### 5.1 Color tokens

The production implementation should expose semantic CSS custom properties rather than hard-coded page colors.

| Token | Reference value | Purpose |
| --- | --- | --- |
| `--fn-canvas` | `#f2eee2` | Primary page background and light sheet background |
| `--fn-ink` | `#25251f` | Primary text, strong rules, and dark surfaces |
| `--fn-ink-soft` | `#4f4f48` | Long-form body text |
| `--fn-muted` | `#6e6d64` | Secondary metadata and captions |
| `--fn-rule` | `#aaa79d` | Dividers, quiet borders, and inactive controls |
| `--fn-accent` | `#b44832` | Active navigation, editorial emphasis, and errors when paired with text or an icon |
| `--fn-positive` | `#789177` | Confirmed and completed states |
| `--fn-dark-surface` | `#2b2d28` | High-contrast figures, technical panels, and selected inverse sections |
| `--fn-on-dark` | `#f2eee2` | Text and controls on dark surfaces |
| `--fn-warning-bg` | `#eee0cf` | Warning and assumption background |
| `--fn-error-bg` | `#f2ddd7` | Error background |
| `--fn-focus` | `#315f78` | Keyboard focus outline that remains distinct from status colors |

Reference values are starting points rather than permission to ship inaccessible contrast.
Validate all foreground and background pairs against WCAG 2.2 AA before implementation.
Normal body text and controls must meet a 4.5:1 contrast ratio, and large text and non-text interface graphics must meet a 3:1 ratio.

Use color semantically and sparingly.
No status may rely on color alone.
Every state also needs readable text, an icon, a border treatment, or a structural change.

### 5.2 Typography

The initial implementation should use system fonts and should not add a font dependency.

| Role | Font stack | Weight | Guidance |
| --- | --- | --- | --- |
| Display | `Georgia, "Times New Roman", serif` | 400 | Edition titles, lead headlines, and major values |
| Editorial body | `Georgia, "Times New Roman", serif` | 400 | Narrative rationale, coach notes, and reflective summaries |
| Interface | `Arial, Helvetica, sans-serif` | 400-700 | Navigation, buttons, forms, status, metadata, and tables |
| Monospace | `ui-monospace, SFMono-Regular, Menlo, monospace` | 400-600 | Tokens, raw JSON, runtime details, and machine-readable identifiers |

The system must use a limited type scale.

| Token | Desktop reference | Mobile reference | Use |
| --- | --- | --- | --- |
| `--fn-type-display` | `clamp(4.125rem, 7.5vw, 6.5rem)` | `3.375rem` | One edition title per page |
| `--fn-type-lead` | `clamp(2.8rem, 4.5vw, 4rem)` | `2.75rem` | Lead section titles |
| `--fn-type-story` | `2.25rem` | `2rem` | Meal, workout, and record titles |
| `--fn-type-heading` | `1.5rem` | `1.375rem` | Form groups and secondary sections |
| `--fn-type-body-lg` | `1rem` | `1rem` | Standfirsts and important explanatory copy |
| `--fn-type-body` | `0.875rem` | `0.875rem` | Normal readable content |
| `--fn-type-ui` | `0.75rem` | `0.75rem` | Buttons, controls, and compact metadata |
| `--fn-type-label` | `0.6875rem` | `0.6875rem` | Uppercase section labels with tracking |

Do not set meaningful interface text below `0.6875rem` in production, even where the static prototype uses smaller mock labels.
Use a body line height between 1.5 and 1.7 for explanatory content.
Keep editorial headlines tight at approximately 0.9 to 1.05 line height.
Avoid more than two emphasized type treatments in the same section.

Italics should highlight one phrase in a major editorial headline or serve their normal grammatical purpose.
Do not use italics for status, actions, form help, errors, or long paragraphs.

### 5.3 Spacing

Use a consistent spacing scale based on four pixels.

```css
--fn-space-1: 0.25rem;
--fn-space-2: 0.5rem;
--fn-space-3: 0.75rem;
--fn-space-4: 1rem;
--fn-space-6: 1.5rem;
--fn-space-8: 2rem;
--fn-space-12: 3rem;
--fn-space-16: 4rem;
--fn-space-20: 5rem;
--fn-space-24: 6rem;
```

Use `--fn-space-12` through `--fn-space-24` to separate editorial chapters.
Use `--fn-space-2` through `--fn-space-6` inside controls and compact operational groups.
Large blank space is structural only when the following section is clearly introduced by a rule, heading, or change in column layout.

### 5.4 Page geometry

- Set the primary content width to `min(100% - 2 * page padding, 1282px)`.
- Use `42px` horizontal page padding on wide screens and `18px` below the mobile breakpoint.
- Keep long-form prose between 52 and 72 characters per line.
- Use asymmetric columns when one section is clearly the lead and the other is supporting evidence.
- Use symmetric columns for peer items such as two meals or two shopping groups.
- Do not allow decorative whitespace to push the first useful action below the initial mobile viewport.

### 5.5 Rules, borders, radius, and shadow

Rules are the main grouping mechanism.
Use one-pixel borders in `--fn-rule` for normal separation and `--fn-ink` for major chapter boundaries.

Most inline surfaces should have no radius.
Circular stamps, pills, switches, check controls, and floating mobile navigation may use a full radius.
Sheets may remain square on desktop and use a small radius only when presented as a centered modal rather than a side sheet.

Do not apply shadows to normal page sections.
Use shadows only for overlays, floating navigation, transient notices, and elements that must visibly sit above the document plane.

### 5.6 Iconography and illustration

Use text, rules, simple geometric marks, and inline SVG before adding an icon library.
Do not add an icon dependency solely for this migration.

Icons must be simple, single-color, and understandable at 16 to 20 pixels.
Every icon-only button needs an accessible name.

Decorative food illustrations may use abstract CSS or inline SVG shapes.
They must use `aria-hidden="true"` and must never communicate quantities, status, or ingredients that are not also present as text.

Training graphics should depict interval structure or an abstract progress figure.
They must not resemble an actual route unless the product has an approved, privacy-reviewed route feature backed by real data.

### 5.7 Motion

Use motion to explain layer changes and state changes.
Do not use ambient animation, parallax, bouncing, or decorative looping motion.

- Page or section entry: 180 to 300 milliseconds with opacity and no more than 8 pixels of vertical translation.
- Sheet entry: 200 to 280 milliseconds with opacity and no more than 30 pixels of horizontal translation.
- Status update: 120 to 180 milliseconds.
- Hover movement: no more than 2 pixels.

Respect `prefers-reduced-motion: reduce` by removing nonessential transforms and smooth scrolling.

## 6. Responsive model

Use content-driven breakpoints close to the prototype references rather than device names.

| Breakpoint | Behavior |
| --- | --- |
| Above `920px` | Full masthead, editorial columns, side sheets, and margin annotations |
| `721px` to `920px` | Reduced column gaps, collapsed secondary stamps, and two-column content where safe |
| `431px` to `720px` | Single-column stories, bottom primary navigation, full-width sheets, and simplified metadata |
| At or below `430px` | Tighter display type, stacked facts, and no nonessential side metadata |

Desktop and mobile must expose the same features and states.
Responsive adaptation may change order and density, but it must not remove actions, provenance, warnings, or correction paths.

On mobile, the bottom navigation must not cover the active control or the final content row.
Reserve safe-area and navigation space in the page padding.
Sheets must remain dismissible, scrollable, keyboard accessible, and safe with the on-screen keyboard.

## 7. Information architecture

### 7.1 Primary destinations

Derive the production navigation from the complete route and feature inventory on the branch being migrated.
The prototype’s Today, Archive, and Provisions labels demonstrate visual treatment, not a complete or authoritative production sitemap.

- Preserve every current destination and external link during the visual migration.
- Preserve current route paths, redirect behavior, deep links, query parameters, back-button behavior, and active-navigation behavior unless a separate approved change says otherwise.
- Keep frequent destinations visible and place low-frequency utilities in an accessible utility area only when that does not reduce discoverability.
- Do not hide a current destination in overflow solely to make the masthead resemble the prototype.
- Use the Field Notes active rule, typographic restraint, and responsive bottom-navigation treatment after the current navigation model has been mapped.
- If the complete navigation cannot fit the prototype composition, propose an adapted composition and obtain approval before implementing it.

### 7.2 Page anatomy

Every authenticated page should use the following sequence when relevant:

1. Masthead and navigation.
2. Edition metadata with date, locale, source, or scope.
3. One page title that describes the user’s context.
4. A concise standfirst or summary derived from existing data.
5. The lead task, story, or form for the page.
6. Supporting sections separated by folio rules.
7. Technical, provenance, or audit details near the end or in a sheet.
8. Transient feedback that does not displace the document.

Transactional pages such as Settings may use a compact edition header and should not force a decorative narrative structure onto form-heavy content.

## 8. Voice and content rules

Use concise, direct language.
Prefer “Mark as eaten,” “Record workout,” and “Review extraction” over clever labels.

Editorial headlines may summarize existing rationale, but they must not add medical, recovery, nutrition, or performance claims.
If the API only provides a technical title, display that title rather than inventing a more poetic claim in the browser.

Use the following content hierarchy:

- Display headline: meaning of the current section, derived from real data or a fixed neutral label.
- Standfirst: one or two sentences explaining why the section matters.
- Section label: category, date, time, source, or state.
- Body copy: instructions or evidence.
- Caption: provenance, assumptions, system details, or privacy notes.

Do not call AI-generated content “smart,” “magical,” or certain.
Use “AI planned,” “AI-assisted analysis,” “Validated proposal,” and “Review before saving” where those labels accurately describe the flow.

## 9. Component system

Components should separate visual structure from domain behavior.
Presentational components receive state and callbacks from existing page logic.
They must not call APIs directly unless the current architecture already places that behavior in the component and the migration plan explicitly preserves it.

The components below are reference patterns derived from the Field Notes visual language.
They are not an inventory of the application and must not replace the future agent’s current-branch component audit.
Use only the patterns that match discovered capabilities, adapt them through the approval process when needed, and add every required production component to the migration-time registry.

### 9.1 `AppMasthead`

Purpose: provide persistent brand, primary navigation, current-route state, record access, Settings, and the Study link.

- Desktop uses the three-column masthead from the prototype.
- Mobile uses a compact top identity plus a fixed bottom destination bar.
- The active destination uses the accent rule and `aria-current="page"`.
- The record action remains visually distinct from destination navigation.
- Any overflow menu must be fully keyboard navigable and close on Escape or outside click.

### 9.2 `EditionMeta`

Purpose: present date, location, source, range, or page scope in a quiet publication line.

- Use one to three items.
- Keep the most important item first in DOM order on mobile.
- Do not put mutable actions inside this component.
- Use semantic `<time>` elements for dates and timestamps.

### 9.3 `EditionHeader`

Purpose: establish one clear page title, optional date folio, optional factual stamp, and optional standfirst.

- Support `hero` and `compact` variants.
- Reserve the hero variant for the primary daily page, and use it only when its message communicates current, useful information.
- Preserve the daily hero's date folio on the left and circular readiness score on the right at desktop sizes.
- When today's planned exercise is complete and coach feedback is available, use that concise feedback as the daily hero message.
- Before the planned exercise is complete, summarize today's exercise program and meals in one short headline and no more than two short supporting sentences.
- If completed exercise feedback is unavailable, show a factual completion summary from existing data rather than inventing coach feedback.
- Use the compact variant for Archive, Shopping or Provisions, Settings, login-related states, and dense historical detail.
- Never use an oversized generic statement merely to fill a page header.
- A stamp must display real state or a real value.
- If no suitable value exists, omit the stamp rather than filling the space with mock data.

### 9.4 `FolioRule`

Purpose: separate major sections and expose a short section title and optional sequence number.

- Use no more than four on a normal page.
- Sequence numbers express visual reading order only and must not replace semantic headings.
- Render a real heading element adjacent to or inside the rule.

### 9.5 `StorySection`

Purpose: frame a major item such as the workout, one meal, the next preparation action, or a historical insight.

- Accept title, label, summary, facts, action region, illustration region, and status region.
- Support lead, standard, compact, and inverse variants.
- Do not accept arbitrary HTML as a shortcut around component consistency.
- Preserve semantic heading order chosen by the page.

### 9.6 `FactList`

Purpose: show measurable values such as protein, active time, distance, effort, source, and schedule.

- Use a semantic `<dl>`.
- Show two to four facts in the default view.
- Move additional values into the detail sheet.
- Never display an unavailable value as zero unless zero is the actual recorded value.

### 9.7 `StatusLabel`

Purpose: render the complete status vocabulary discovered on the branch as quieter, explicit editorial state language.

- Inventory every status value, its domain meaning, and its current visual and behavioral effect before designing the mapping.
- Publish the proposed label and treatment for every discovered value in the migration plan.
- Distinguish ordinary, positive, cautionary, error, locked, and historical states using text and structure as well as color.
- Map status centrally in one typed component or a similarly authoritative shared layer.
- Do not scatter status strings or CSS selectors across pages.
- Unknown statuses must remain visible as humanized text and must never silently render as a familiar default.
- Adding, merging, or changing the meaning of a status is product logic and requires approval.

### 9.8 `ActionButton` and `TextAction`

Purpose: create a restrained but consistent action hierarchy.

- Primary actions use an ink-filled control and should appear once per local task group.
- Secondary actions use a one-pixel outline or underlined text.
- Destructive actions use explicit language and the accent color only when the action is genuinely destructive.
- Disabled actions retain their label and expose the reason in adjacent text or an accessible description.
- Loading actions replace the verb with a precise progress label such as “Analyzing” or “Saving.”
- Buttons must have a minimum interactive target of 44 by 44 CSS pixels on touch layouts.

### 9.9 `DetailSheet`

Purpose: reveal recipes, workout details, coach conversation, extraction review, system details, and editing forms without turning the page into a stack of cards.

- Use the native `<dialog>` element or an equally accessible dialog implementation.
- Set an accessible name using the visible title.
- Move focus into the sheet when opened and return focus to the trigger when closed.
- Close on Escape unless an in-flight operation or unsaved edit requires a confirmation.
- Trap focus while open.
- Prevent background scrolling.
- Use a full-height right sheet on desktop and a full-width sheet on mobile.
- Long content must scroll inside the sheet without hiding the close control or primary action.

### 9.10 `RecordDrawer`

Purpose: host a discovered free-text, structured, or multi-mode recording flow without overwhelming the default page.

- Preserve every mode, existing value, step, consequence, privacy note, and provider note found during the branch audit.
- Clearly distinguish analysis, review, submission, persistence, replacement, and re-analysis wherever the current flow distinguishes them.
- Keep irreversible or authoritative consequences beside the submission action.
- Do not combine multiple current steps or shorten the flow without explicit approval.

### 9.11 `ReviewEditor`

Purpose: present extracted or proposed records for validation before persistence when such a workflow exists.

- Use one bordered editorial record per review item rather than a generic card grid.
- Preserve every discovered field, validation range, match, add action, delete action, safety control, and ownership rule.
- Display validation errors beside the affected record and summarize blocking errors near the final submit action.
- Preserve any requirement to re-run analysis after the source changes.

### 9.12 `CoachConversation` and `ConversationSheet`

Purpose: present discovered coaching, assistant, commentary, or conversation capabilities in a personal but evidence-conscious form.

- Use the bottom coaching section on the primary daily page as an ongoing AI chat, not as a one-way letter.
- Show enough recent chronological history inline to make the current exchange understandable.
- Provide an explicit route or `ConversationSheet` for the complete available history and continued conversation.
- Clearly distinguish user and AI messages without relying on color alone.
- Include sender identity and a meaningful timestamp for every persisted message.
- Keep the composer close to the history, preserve draft and sending states, and make delivery or failure status accessible.
- Do not present a mock AI reply as real or imply persistence the current product does not provide.
- Preserve every discovered distinction between explanation, proposal, current state, applied change, and historical record.
- Do not rewrite returned content in the frontend to make it sound more editorial.

### 9.13 `RecordList` and `DateIndex`

Purpose: support dated navigation and dense historical or audit evidence when those capabilities exist.

- Desktop may use a sticky date index beside the selected day.
- Mobile should use a horizontally scrollable or select-based date navigator without hiding count and source information.
- Records must show every discovered title, status, source, measurement, safety field, note, and provider link when present.
- Correction actions should open an accessible form sheet rather than use `window.prompt` in the target design.
- Replacing `window.prompt` with a form is presentational only if it submits the exact same existing payload and validation rules.

### 9.14 `FormSection`, `Field`, and `ChoiceRow`

Purpose: keep every discovered form, correction, review, setup, and integration control consistent.

- Use visible labels above controls.
- Keep help text close to the field it explains.
- Use a two-column field grid only when labels and values remain readable.
- Collapse to one column on mobile.
- Group related fields under a real heading and short description.
- Preserve native input semantics and browser affordances.
- Do not use placeholder text as the only label.
- Display saved, loading, warning, and error feedback in a stable region that does not cause large layout shifts.

### 9.15 `Notice`

Purpose: communicate success, error, warning, privacy, lock, empty, and informational states.

- Error notices use `role="alert"` when immediate announcement is necessary.
- Success feedback uses `role="status"` and should not steal focus.
- Lock notices explain why an action is unavailable and identify the correct next path.
- Empty states explain what is absent without implying that valid rest or no-entry days are failures.
- Use inline notices for persistent information and toasts only for brief confirmation.

### 9.16 `LoadingState` and `ErrorState`

Purpose: prevent every route from inventing its own loading and error appearance.

- Loading states should preserve the expected page measure and avoid a large centered spinner.
- Use a quiet progress sentence or editorial skeleton with reduced motion support.
- Error states must preserve the user’s location and offer a retry when the existing query can safely retry.
- Never swallow the API’s safe error message.

## 10. Page archetypes

The implementing agent must assign every current route to an archetype after completing the branch audit.
These archetypes describe composition only and do not prescribe or remove features.

### 10.1 Daily sequence

Use for a date-oriented plan, agenda, or collection of actions.
Communicate sequence before category while retaining every current section, state, action, and temporal restriction.
The first viewport should include the temporal context, section identity, current state, and most important available action.
Keep the date folio and readiness score as the stable visual anchors of the daily hero where those values exist.
Use the hero center for concise coach feedback after exercise completion, or a concise exercise-and-meal plan summary before completion.
Build this content from authoritative current data and never invent a score, plan detail, or coach response.

### 10.2 Archive and evidence

Use for historical records, audits, source material, corrections, and comparisons.
Prioritize evidence and provenance over inspirational summary.
Use editorial summaries only when directly returned by current data or safely derived without changing meaning.
Use a compact functional page header instead of an oversized generic hero.

### 10.3 Operational list

Use for shopping, inventory, tasks, integrations, equipment, or other actionable collections.
Keep filters, totals, confidence, source, bulk actions, item actions, and empty states discoverable whenever they exist on the current branch.
Do not imply persistence or item-level behavior that the current product does not support.
Use a compact functional page header, with real counts or totals when helpful, instead of an oversized generic hero.

### 10.4 Configuration

Use for settings, profile, integrations, credentials, and rule management.
Use a compact editorial header and disciplined form sections rather than repeated narrative headlines.
Visually isolate sensitive output and clearly distinguish destructive actions from routine actions.

### 10.5 Authentication and focused task

Use for login, authorization callbacks, one-time setup, and other focused flows.
Use the Field Notes canvas, brand mark, one concise title, and a single clear task.
Preserve the current security and redirect behavior and do not show controls that are unavailable in the current state.

## 11. State and provenance language

During branch discovery, identify every independent state dimension represented in schemas, UI code, domain logic, and tests.
Typical dimensions may include lifecycle status, evidence source, temporal context, safety state, ownership, confidence, validation state, and synchronization state.

Do not compress independent dimensions into one badge.
A lifecycle state and its provenance should remain separately readable when the product distinguishes them.

Use positive green only for a confirmed fact or successful operation.
Use accent red for attention, current navigation, genuine errors, and safety warnings.
Do not use red for neutral, optional, restful, unavailable, skipped, or historical states unless the current domain explicitly treats them as errors.

## 12. Accessibility requirements

- Meet WCAG 2.2 AA for color, focus, keyboard interaction, labeling, and target size.
- Preserve a logical heading hierarchy even when the visual type size differs.
- Provide a visible `:focus-visible` outline using `--fn-focus` with at least two pixels of thickness and sufficient offset.
- Ensure all sheets, tabs, disclosures, and menus work with keyboard alone.
- Use actual buttons for actions and actual links for navigation.
- Announce mutation results with appropriate live regions.
- Associate validation messages with fields using `aria-describedby`.
- Expose current tabs with `aria-selected` and current navigation with `aria-current`.
- Ensure decorative drop caps, folio numbers, and illustrations do not create noisy screen-reader output.
- Do not force uppercase through source text because screen readers may pronounce acronyms unexpectedly.
- Test at 200 percent browser zoom and with text spacing overrides.
- Respect reduced motion, dark-mode user preferences only if an approved dark Field Notes theme exists, and platform high-contrast modes.

## 13. Consistency rules for future components

Before adding a new component, the implementing agent must answer these questions in its plan:

1. Which existing component cannot express the requirement?
2. Is the need presentational, interaction logic, domain logic, or data acquisition?
3. Which tokens, typography role, spacing rhythm, and responsive behavior will it use?
4. What are its loading, empty, error, disabled, locked, success, and historical states?
5. How does it expose provenance and safety information?
6. How will it work with keyboard, screen readers, zoom, and reduced motion?
7. Does it require a new dependency, API field, endpoint, persistence rule, route, or background behavior?
8. Which tests will prove that current behavior remains intact?

Every new component must appear in the migration-time component registry and receive approval before implementation.
If a component is discovered after that registry is approved, the agent must stop after writing the component proposal and request approval even when it is purely presentational.
If the answer to question 7 is yes, the agent must also separate the product or technical change from the visual component proposal and request approval.
The agent must not implement a new component or new logic speculatively.

Prefer extending an existing component with a well-defined variant when the semantic role is the same.
Create a new component when the semantic role, interaction model, or accessibility contract is different.
Do not create one-off page components that duplicate status mapping, sheet behavior, form feedback, or action hierarchy.

## 14. Design review checklist

Every migrated route and every new component must pass this checklist before handoff.

### Visual hierarchy

- The page has one primary title and one obvious next action.
- Supporting information is quieter without becoming illegible.
- Sections are grouped primarily by structure and rules rather than repeated cards.
- Editorial styling clarifies the product rather than adding fictional narrative.

### Behavior

- Every previous action is still present and calls the same API with the same payload unless separately approved.
- Every disabled, locked, loading, empty, success, and error state is represented.
- Current and historical behavior remain distinct.
- Recommendation, actual, assumption, and provenance remain distinct.

### Consistency

- Colors, typography, spacing, rules, controls, sheets, status, and feedback use shared tokens or components.
- No page introduces a private button, badge, dialog, form, or error style without a documented reason.
- Responsive behavior follows the shared breakpoints and preserves feature access.

### Accessibility

- Keyboard traversal follows the visual order.
- Focus is always visible and correctly managed across overlays.
- Color contrast and target sizes pass.
- Screen-reader names and state announcements are present.
- The route works at 200 percent zoom and at the narrow supported viewport.

## 15. Reference implementation boundaries

The static prototype is a visual reference, not production code to copy wholesale.
Its mock data, tiny label sizes, simplified forms, generic timers, readiness score, route illustration, sample navigation, and condensed content are not authoritative product requirements.

Production implementation should reuse the prototype’s composition, restraint, palette, typography, rules, and layer model.
It should use the framework, routes, data contracts, security model, domain behavior, and tests present on the branch at migration time as the functional source of truth.
