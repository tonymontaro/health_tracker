import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";

type PlannedMeal = {
  template_name: string;
  description: string;
  expected: boolean;
  hands_on_minutes: number;
  total_minutes?: number;
  estimated_protein_g: number;
  ingredients: string[];
  preparation: string;
  special?: boolean;
};
type MealDay = {
  plan_date: string;
  meals: PlannedMeal[];
  fruits: Array<{ name: string; quantity: string }>;
  snacks: Array<{ name: string; description: string }>;
  guidance: string;
  changed?: boolean;
};
type MealWeek = {
  week_start: string;
  week_end: string;
  source: string;
  days: MealDay[];
};
type MealPeriod = {
  start_date: string;
  end_date: string;
  weeks: MealWeek[];
  changed: boolean;
  shopping: {
    items: Array<{ food_name: string; quantity_label: string }>;
    notes: string[];
    copy_text: string;
  };
};
type MealCalendar = { today: string; periods: MealPeriod[] };

function dateLabel(value: string, weekday = false) {
  return new Date(`${value}T12:00:00`).toLocaleDateString(undefined, {
    ...(weekday ? { weekday: "long" as const } : {}),
    month: "short",
    day: "numeric",
  });
}

function shoppingResearchPrompt(period: MealPeriod): string {
  const items = period.shopping.items
    .map((item) => `${item.food_name}: ${item.quantity_label}`)
    .join("\n");

  return `Please browse the web and turn this two-week shopping list into specific products I can buy in Zurich, Switzerland.

Find products at Swiss online grocery retailers such as Migros or Coop, preferably from one retailer for a single delivery.
This order covers one main meal per day for one person, plus the listed snacks, fruit and nuts. Include all of those listed quantities. Optional meal ingredients are excluded; do not add them.

For every listed ingredient:
- Link directly to a verified product page.
- Give the product and brand name, pack size, number of packs needed, current price in CHF and subtotal. Round up to whole packs that cover the requested quantity.
- Respect cooked weights: find ready-cooked grains or cooked/drained pulses and use drained weights where relevant.
- Prefer frozen or suitable long-life products for the second week, and identify items to freeze on arrival.
- If unavailable, clearly label a close nutritional and practical substitute and explain the difference.
- Do not invent products, prices, availability or links. Mark anything you cannot verify. Do not omit any ingredient.

Return a concise Markdown table with: Requested ingredient, Recommended product, Pack size, Packs to buy, Price, Subtotal, Direct link, Notes.
Then give the estimated basket total, delivery fees if verified, any items needing clarification, and availability that depends on postcode.

${items}`;
}

function ShoppingList({ period }: { period: MealPeriod }) {
  const [copyStatus, setCopyStatus] = useState("");
  const [manualCopy, setManualCopy] = useState<{
    label: string;
    text: string;
  } | null>(null);
  async function copy(kind: "list" | "prompt") {
    const text =
      kind === "list"
        ? period.shopping.copy_text
        : shoppingResearchPrompt(period);
    const label = kind === "list" ? "Shopping list" : "AI search prompt";
    try {
      await navigator.clipboard.writeText(text);
      setCopyStatus(
        kind === "list"
          ? "Shopping list copied."
          : "AI search prompt copied. Ready to paste into an AI chatbot.",
      );
      setManualCopy(null);
    } catch {
      setManualCopy({ label, text });
      setCopyStatus(`Select and copy the ${label.toLowerCase()} below.`);
    }
  }
  return (
    <aside
      className="meal-week-shopping card"
      id={`shopping-${period.start_date}`}
    >
      <p className="eyebrow">One order / two weeks</p>
      <h3>Shopping list</h3>
      <p>
        Monday {dateLabel(period.start_date)} to Sunday{" "}
        {dateLabel(period.end_date)}. Arrange delivery by the first Monday.
      </p>
      <p>
        Main meals, snacks, fruit and nuts are included. Buy optional meal
        ingredients on the day if you want to prepare one.
      </p>
      <div className="meal-copy-actions">
        <button
          className="primary"
          type="button"
          onClick={() => void copy("list")}
        >
          Copy shopping list
        </button>
        <button
          className="quiet"
          type="button"
          onClick={() => void copy("prompt")}
        >
          Copy AI search prompt
        </button>
      </div>
      <p className="copy-status" role="status">
        {copyStatus}
      </p>
      {manualCopy && (
        <label>
          {manualCopy.label} to copy
          <textarea
            readOnly
            rows={12}
            value={manualCopy.text}
            onFocus={(event) => event.currentTarget.select()}
          />
        </label>
      )}
      {period.changed && (
        <p className="meal-plan-notice">
          Includes changes made to meals or extras. Check this list again if you
          have already ordered.
        </p>
      )}
      <ul className="meal-groceries">
        {period.shopping.items.map((item) => (
          <li key={`${item.food_name}-${item.quantity_label}`}>
            <span>{item.food_name}</span>
            <strong>{item.quantity_label}</strong>
          </li>
        ))}
      </ul>
      <details className="meal-shopping-notes">
        <summary>Quantities and delivery notes</summary>
        <ul>
          {period.shopping.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      </details>
    </aside>
  );
}

function MealWeekView({ week, today }: { week: MealWeek; today: string }) {
  return (
    <section
      className="meal-week-days"
      aria-label={`Week of ${week.week_start}`}
    >
      <h3 className="meal-calendar-week-heading">
        {dateLabel(week.week_start)} - {dateLabel(week.week_end)}
      </h3>
      {week.source === "fallback" && (
        <p className="meal-plan-notice">
          Using a saved fallback meal plan. AI planning was unavailable when
          this week was created.
        </p>
      )}
      {week.days.map((day) => (
        <article
          className={`meal-calendar-day${day.plan_date === today ? " is-today" : ""}${day.plan_date < today ? " is-past" : ""}`}
          key={day.plan_date}
        >
          <header>
            <h4>
              <time dateTime={day.plan_date}>
                {dateLabel(day.plan_date, true)}
              </time>
            </h4>
            <span>
              {day.plan_date === today
                ? "Today"
                : day.plan_date < today
                  ? "Earlier this period"
                  : ""}
            </span>
          </header>
          <div className="meal-day-recipes">
            {day.meals.map((meal, index) => (
              <details
                className="meal-planned-recipe"
                key={`${index}-${meal.template_name}`}
              >
                <summary>
                  <span className="eyebrow">
                    {meal.expected
                      ? "Main meal / in your order"
                      : "Optional / buy on the day"}
                    {meal.special ? " / Sunday cooking" : ""}
                  </span>
                  <strong>{meal.template_name}</strong>
                  <span>
                    {meal.hands_on_minutes} min hands-on
                    {meal.total_minutes
                      ? ` · ${meal.total_minutes} min total`
                      : ""}{" "}
                    · Recipe +
                  </span>
                </summary>
                <div className="meal-recipe-body">
                  <p>{meal.description}</p>
                  <p>
                    <strong>One serving</strong> · Approx.{" "}
                    {meal.estimated_protein_g} g protein
                  </p>
                  <ul>
                    {meal.ingredients.map((ingredient) => (
                      <li key={ingredient}>{ingredient}</li>
                    ))}
                  </ul>
                  <p>{meal.preparation}</p>
                </div>
              </details>
            ))}
          </div>
          <p className="meal-day-extras">
            Fruit, snacks & nuts / in your order:{" "}
            {[
              ...day.fruits.map((fruit) => `${fruit.quantity} ${fruit.name}`),
              ...day.snacks.map(
                (snack) => `${snack.name}, ${snack.description}`,
              ),
            ].join(" · ")}
          </p>
          <details className="meal-day-guidance">
            <summary>Fueling guidance</summary>
            <p>{day.guidance}</p>
          </details>
        </article>
      ))}
    </section>
  );
}

export function MealPlanPage() {
  const plan = useQuery({
    queryKey: ["meal-plan"],
    queryFn: () => api<MealCalendar>("/meals/plan", { method: "POST" }),
    staleTime: 60_000,
    refetchInterval: 60_000,
  });
  return (
    <div className="field-notes-edition meal-calendar">
      {plan.isLoading && (
        <div className="loading" role="status">
          Preparing your meals and two-week shopping list. The first plan can
          take a few minutes...
        </div>
      )}
      {plan.error && (
        <div className="error-panel" role="alert">
          <p>{plan.error.message}</p>
          <button
            className="quiet"
            type="button"
            onClick={() => void plan.refetch()}
          >
            Try again
          </button>
        </div>
      )}
      {plan.data && (
        <>
          <nav className="meal-week-links" aria-label="Shopping periods">
            {plan.data.periods.map((period, index) => (
              <a href={`#period-${period.start_date}`} key={period.start_date}>
                {index === 0 ? "Current two weeks" : "Next two weeks"} ·{" "}
                {dateLabel(period.start_date)}
              </a>
            ))}
          </nav>
          {plan.data.periods.map((period) => (
            <section
              className="meal-week"
              id={`period-${period.start_date}`}
              key={period.start_date}
            >
              <header className="meal-week-heading">
                <div>
                  <p className="eyebrow">Two weeks / one shopping list</p>
                  <h2>
                    {dateLabel(period.start_date)} -{" "}
                    {dateLabel(period.end_date)}
                  </h2>
                </div>
                <a href={`#shopping-${period.start_date}`}>
                  View shopping list ↓
                </a>
              </header>
              <div className="meal-week-layout">
                <div>
                  {period.weeks.map((week) => (
                    <MealWeekView
                      week={week}
                      today={plan.data.today}
                      key={week.week_start}
                    />
                  ))}
                </div>
                <ShoppingList period={period} />
              </div>
            </section>
          ))}
        </>
      )}
    </div>
  );
}
