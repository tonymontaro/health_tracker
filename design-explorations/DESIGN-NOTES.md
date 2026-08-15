# Health Autopilot design evaluation

## Current experience

The current interface is competent, cohesive, and unusually complete for a personal planning product.
Its warm palette, consistent controls, plain-language copy, visible provenance, and responsive single-column fallback all give it a solid foundation.
The underlying product model is also strong because recommendations, actual records, AI-assisted analysis, and historical corrections remain separate.

The main design problem is hierarchy rather than missing functionality.
Most information is presented as a bordered card with a heading, body copy, metadata pills, and action row.
This makes a meal, a safety fallback, a daily action, a recording workflow, and a coaching conversation look equally important even though they serve very different moments.

The Today experience also combines several interaction models in one long page.
Users can confirm structured recommendations, replace them with a free-text actual record, regenerate part of the plan, retrieve provider data, edit extracted fields, and ask the coach for a change.
Those capabilities are valuable, but the default view exposes too much of their machinery before the user has chosen what they need to do.

The Food and Exercise split is clear for the data model but weaker as a representation of a real day.
A person usually thinks in a sequence such as eat, prepare, train, recover, and record.
The current navigation makes that sequence harder to perceive because the next action, meals, workout, optional items, and coach live in separate cards or tabs.

Finally, the visual identity is polished but familiar.
Muted cream, green, rounded cards, serif headings, and pill-shaped metadata are common across modern wellness products.
The app needs a more ownable interaction idea as much as it needs a more distinctive palette.

## Design opportunities

1. Make the next useful action the primary unit of the Today experience.
2. Show the whole day as a rhythm while keeping Food and Exercise available as focused views.
3. Reveal recipes, plan rationale, extraction review, and editing tools only when requested.
4. Use distinct visual treatments for recommendations, actuals, safety fallbacks, and system or AI activity.
5. Keep rest, skipping, correction, and changing the plan visually normal rather than framing completion as the only successful outcome.
6. Move system explanations and privacy details close to the relevant action without letting them dominate the default state.
7. Preserve a compact, information-rich mode for History, Shopping, and record correction even if Today becomes much calmer.

## Selected direction

Field Notes is the selected design direction.
Its editorial daybook structure gives the product a calm, human, and ownable identity while keeping operational detail available on demand.
The design system and migration prompt define how this visual language should adapt to the complete feature set found on the target branch.

The next iteration should validate Field Notes against real API states before changing the production interface.
Important states include a rest day, one-meal day, completed and skipped recommendations, a locked food log, reviewed workout extraction, a Strava match, pain feedback, a historical date, regeneration errors, and an empty shopping list.
