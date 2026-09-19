import { useQuery } from "@tanstack/react-query";
import { type MouseEvent, useId, useLayoutEffect, useRef, useState } from "react";
import { api } from "../api/client";

type CalendarMonth = {
  today: string;
  month: string;
  first_plan_date: string | null;
  days: Array<{ date: string; has_plan: boolean; exercise_performed: boolean }>;
};

function localDate(value: string): Date {
  return new Date(`${value}T12:00:00`);
}

function dateKey(value: Date): string {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
}

function adjacentMonth(month: string, offset: number): string {
  const value = localDate(month);
  return dateKey(new Date(value.getFullYear(), value.getMonth() + offset, 1, 12));
}

function CalendarIcon() {
  return <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="1" /><path d="M7 2v6M17 2v6M3 11h18M7 15h3M14 15h3" /></svg>;
}

export function DailyPlanCalendar({ selectedDate, currentDate, onSelect }: {
  selectedDate: string;
  currentDate: string;
  onSelect: (date: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const label = localDate(selectedDate).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric", year: "numeric" });
  return <div className="date-selector">
    <span className="date-selector-label">Daily plan</span>
    <button type="button" className="date-calendar-trigger" aria-haspopup="dialog" aria-expanded={open} aria-label={`Choose plan date, ${label}`} onClick={() => setOpen(true)}>
      <CalendarIcon /><span>{selectedDate === currentDate ? "Today · " : ""}{label}</span><span aria-hidden="true">⌄</span>
    </button>
    {open && <CalendarDialog selectedDate={selectedDate} currentDate={currentDate} onClose={() => setOpen(false)} onSelect={(date) => { onSelect(date); setOpen(false); }} />}
  </div>;
}

function CalendarDialog({ selectedDate, currentDate, onClose, onSelect }: {
  selectedDate: string;
  currentDate: string;
  onClose: () => void;
  onSelect: (date: string) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  const currentMonth = `${currentDate.slice(0, 7)}-01`;
  const [month, setMonth] = useState(currentMonth);
  const calendar = useQuery({
    queryKey: ["daily-calendar", month],
    queryFn: () => api<CalendarMonth>(`/today/calendar?month=${month}`),
    staleTime: 0,
  });
  useLayoutEffect(() => {
    const current = dialog.current;
    current?.showModal();
    return () => current?.close();
  }, []);
  const first = localDate(month);
  const monthLabel = first.toLocaleDateString(undefined, { month: "long", year: "numeric" });
  const offset = (first.getDay() + 6) % 7;
  const length = new Date(first.getFullYear(), first.getMonth() + 1, 0, 12).getDate();
  const weeks = Math.ceil((offset + length) / 7);
  const calendarDays = new Map(calendar.data?.days.map((day) => [day.date, day]));
  const earliestMonth = calendar.data?.first_plan_date?.slice(0, 7);
  const canGoBack = Boolean(earliestMonth && month.slice(0, 7) > earliestMonth);
  const selectedLabel = localDate(selectedDate).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  function closeOnBackdrop(event: MouseEvent<HTMLDialogElement>) {
    if (event.target !== event.currentTarget) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) onClose();
  }
  return <dialog className="daily-calendar-dialog" ref={dialog} aria-labelledby={titleId} aria-describedby={descriptionId} onCancel={onClose} onClick={closeOnBackdrop}>
    <div className="calendar-heading"><div><p className="eyebrow">Your daily plans</p><h2 id={titleId}>Choose a day</h2></div><button type="button" className="calendar-close" aria-label="Close calendar" onClick={onClose}>×</button></div>
    <p id={descriptionId} className="calendar-description">Open a saved exercise and food plan. Days without recommendations are unavailable.</p>
    <div className="calendar-month-nav">
      <button type="button" aria-label="Previous month" disabled={!canGoBack || calendar.isFetching} onClick={() => setMonth(adjacentMonth(month, -1))}>‹</button>
      <h3 aria-live="polite">{monthLabel}</h3>
      <button type="button" aria-label="Next month" disabled={month >= currentMonth || calendar.isFetching} onClick={() => setMonth(adjacentMonth(month, 1))}>›</button>
    </div>
    <div className="calendar-grid-container" aria-busy={calendar.isFetching}>
      <table className="calendar-grid" aria-label={monthLabel}>
        <thead><tr>{["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"].map((day) => <th scope="col" key={day} abbr={day}>{day.slice(0, 2)}</th>)}</tr></thead>
        <tbody>{Array.from({ length: weeks }, (_, week) => <tr key={week}>{Array.from({ length: 7 }, (_, weekday) => {
          const day = week * 7 + weekday - offset + 1;
          if (day < 1 || day > length) return <td key={weekday} />;
          const value = `${month.slice(0, 7)}-${String(day).padStart(2, "0")}`;
          const entry = calendarDays.get(value);
          const saved = entry?.has_plan ?? false;
          const performed = entry?.exercise_performed ?? false;
          const today = value === currentDate;
          const selected = value === selectedDate;
          const label = localDate(value).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
          return <td key={weekday}><button type="button" className={`calendar-day${performed ? " has-exercise" : ""}${today ? " is-today" : ""}${selected ? " is-selected" : ""}`} disabled={!saved || calendar.isFetching} aria-label={`${label}${today ? ", today" : ""}${performed ? ", exercise recorded" : ""}${saved ? ", saved plan" : ", no saved plan"}`} aria-current={today ? "date" : undefined} aria-pressed={selected} onClick={() => onSelect(value)}><span>{day}</span>{performed && <i className="calendar-exercise-dot" aria-hidden="true" />}</button></td>;
        })}</tr>)}</tbody>
      </table>
      {calendar.isFetching && <p className="calendar-message" role="status">Loading saved days...</p>}
      {calendar.error && <div className="calendar-message error" role="alert"><p>Could not load saved days.</p><button className="quiet small" type="button" onClick={() => void calendar.refetch()}>Try again</button></div>}
      {calendar.data && !calendar.isFetching && !calendar.error && !calendar.data.days.some((day) => day.has_plan) && <p className="calendar-message">No saved plans this month.{canGoBack ? " Try an earlier month." : ""}</p>}
    </div>
    <div className="calendar-legend"><span><i className="legend-saved" />Saved plan</span><span><i className="legend-exercise" />Exercise recorded</span><span><i className="legend-unavailable" />No plan</span></div>
    <div className="calendar-footer"><small>Viewing {selectedLabel}</small><button type="button" className="text-button" onClick={() => onSelect(currentDate)}>Go to today <span aria-hidden="true">↗</span></button></div>
  </dialog>;
}
