import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";

type PlannedMeal = {
  template_name: string;
  description: string;
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
  changed: boolean;
  shopping: {
    items: Array<{ food_name: string; quantity_label: string }>;
    notes: string[];
    copy_text: string;
  };
};
type MealCalendar = { today: string; weeks: MealWeek[] };

function dateLabel(value: string, weekday = false) {
  return new Date(`${value}T12:00:00`).toLocaleDateString(undefined, {
    ...(weekday ? { weekday: "long" as const } : {}), month: "short", day: "numeric",
  });
}

function ShoppingList({ week }: { week: MealWeek }) {
  const [copyStatus, setCopyStatus] = useState("");
  const [manualCopy, setManualCopy] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(week.shopping.copy_text);
      setCopyStatus("Shopping list copied.");
      setManualCopy(false);
    } catch {
      setManualCopy(true);
      setCopyStatus("Select and copy the list below.");
    }
  }
  return <aside className="meal-week-shopping card" id={`shopping-${week.week_start}`}>
    <p className="eyebrow">Your weekly order</p>
    <h3>Shopping list</h3>
    <p>For Monday {dateLabel(week.week_start)} to Sunday {dateLabel(week.week_end)}. Arrange delivery by Monday.</p>
    <button className="primary" type="button" onClick={() => void copy()}>Copy shopping list</button>
    <p className="copy-status" role="status">{copyStatus}</p>
    {manualCopy && <label>Shopping list to copy<textarea readOnly rows={12} value={week.shopping.copy_text} onFocus={(event) => event.currentTarget.select()} /></label>}
    {week.changed && <p className="meal-plan-notice">Includes changes made to daily meals. Check this list again if you have already ordered.</p>}
    <ul className="meal-groceries">{week.shopping.items.map((item) => <li key={`${item.food_name}-${item.quantity_label}`}><span>{item.food_name}</span><strong>{item.quantity_label}</strong></li>)}</ul>
    <details className="meal-shopping-notes"><summary>Quantities and delivery notes</summary><ul>{week.shopping.notes.map((note) => <li key={note}>{note}</li>)}</ul></details>
  </aside>;
}

export function MealPlanPage() {
  const plan = useQuery({
    queryKey: ["meal-plan"], queryFn: () => api<MealCalendar>("/meals/plan", { method: "POST" }),
    staleTime: 60_000, refetchInterval: 60_000,
  });
  return <div className="field-notes-edition meal-calendar">
    <header className="meal-calendar-heading">
      <div><p className="eyebrow">Eat well / plan ahead</p><h1>Your next two weeks of meals</h1><p>Simple, varied meals for running, cycling and strength. A little more cooking on Sundays.</p></div>
      <Link className="quiet" to="/today/food">Today's meals & recording</Link>
    </header>
    <p className="meal-calendar-intro">At least 14 days ahead, in complete Monday-Sunday weeks. Each week's shopping list covers one person, with fruit and optional snacks included.</p>
    {plan.isLoading && <div className="loading" role="status">Preparing your meal weeks and shopping lists. The first plan can take a few minutes...</div>}
    {plan.error && <div className="error-panel" role="alert"><p>{plan.error.message}</p><button className="quiet" type="button" onClick={() => void plan.refetch()}>Try again</button></div>}
    {plan.data && <>
      <nav className="meal-week-links" aria-label="Meal weeks">{plan.data.weeks.map((week, index) => <a href={`#week-${week.week_start}`} key={week.week_start}>{index === 0 ? "This week" : index === 1 ? "Next week" : "Following week"} · {dateLabel(week.week_start)}</a>)}</nav>
      {plan.data.weeks.map((week) => <section className="meal-week" id={`week-${week.week_start}`} key={week.week_start}>
        <header className="meal-week-heading"><div><p className="eyebrow">Monday to Sunday</p><h2>{dateLabel(week.week_start)} - {dateLabel(week.week_end)}</h2></div><a href={`#shopping-${week.week_start}`}>View shopping list ↓</a></header>
        {week.source === "fallback" && <p className="meal-plan-notice">Using a saved fallback meal plan. AI planning was unavailable when this week was created.</p>}
        <div className="meal-week-layout"><div className="meal-week-days">{week.days.map((day) => <article className={`meal-calendar-day${day.plan_date === plan.data.today ? " is-today" : ""}${day.plan_date < plan.data.today ? " is-past" : ""}`} key={day.plan_date}>
          <header><h3><time dateTime={day.plan_date}>{dateLabel(day.plan_date, true)}</time></h3><span>{day.plan_date === plan.data.today ? "Today" : day.plan_date < plan.data.today ? "Earlier this week" : ""}</span></header>
          <div className="meal-day-recipes">{day.meals.map((meal, index) => <details className="meal-planned-recipe" key={`${index}-${meal.template_name}`}>
            <summary><span className="eyebrow">Meal {index + 1}{meal.special ? " / Sunday cooking" : ""}</span><strong>{meal.template_name}</strong><span>{meal.hands_on_minutes} min hands-on{meal.total_minutes ? ` · ${meal.total_minutes} min total` : ""} · Recipe +</span></summary>
            <div className="meal-recipe-body"><p>{meal.description}</p><p><strong>One serving</strong> · Approx. {meal.estimated_protein_g} g protein</p><ul>{meal.ingredients.map((ingredient) => <li key={ingredient}>{ingredient}</li>)}</ul><p>{meal.preparation}</p></div>
          </details>)}</div>
          <p className="meal-day-extras">{day.fruits.map((fruit) => `${fruit.quantity} ${fruit.name}`).join(" · ")}{day.snacks.length > 0 && ` · Optional: ${day.snacks.map((snack) => `${snack.name}, ${snack.description}`).join("; ")}`}</p>
          <details className="meal-day-guidance"><summary>Fueling guidance</summary><p>{day.guidance}</p></details>
        </article>)}</div><ShoppingList week={week} /></div>
      </section>)}
    </>}
  </div>;
}
