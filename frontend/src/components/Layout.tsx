import { type KeyboardEvent, type MouseEvent, useEffect, useRef } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

const primaryLinks = [
  { to: "/today/exercise", label: "Exercise" },
  { to: "/today/food", label: "Food" },
  { to: "/history", label: "History" },
  { to: "/inventory", label: "Inventory" },
  { to: "/settings", label: "Settings" },
];

function closeDetails(event: MouseEvent<HTMLAnchorElement>) {
  event.currentTarget.closest("details")?.removeAttribute("open");
}

function closeMenuOnEscape(event: KeyboardEvent<HTMLDetailsElement>) {
  if (event.key !== "Escape") return;
  event.currentTarget.removeAttribute("open");
  event.currentTarget.querySelector("summary")?.focus();
}

export function Layout() {
  const mobileMenu = useRef<HTMLDetailsElement>(null);
  const location = useLocation();
  const navigate = useNavigate();
  useEffect(() => {
    function closeOnOutsidePointer(event: PointerEvent) {
      for (const menu of [mobileMenu.current]) {
        if (menu?.open && event.target instanceof Node && !menu.contains(event.target)) menu.removeAttribute("open");
      }
    }
    document.addEventListener("pointerdown", closeOnOutsidePointer);
    return () => document.removeEventListener("pointerdown", closeOnOutsidePointer);
  }, []);
  function openRecorder() {
    const kind = location.pathname.includes("food") || location.pathname.includes("nutrition") ? "food" : "exercise";
    const current = new URLSearchParams(location.search);
    const next = new URLSearchParams({ record: kind });
    const date = current.get("date");
    if (date) next.set("date", date);
    navigate(`/today/${kind}?${next.toString()}`);
  }
  return (
    <div className="app-shell">
      <header className="topbar">
        <NavLink className="brand" to="/today/exercise" aria-label="Health Autopilot, Exercise">
          <span className="brand-mark">HA</span>
          <span className="brand-copy"><b>Health Autopilot</b><small>Personal field notes</small></span>
        </NavLink>
        <nav className="desktop-nav" aria-label="Primary navigation">
          {primaryLinks.map((link) => <NavLink key={link.to} to={link.to}>{link.label}</NavLink>)}
          <a href="https://solve.anthonyngene.com/">Study <span aria-hidden="true">↗</span></a>
        </nav>
        <button className="record-trigger" type="button" aria-haspopup="dialog" onClick={openRecorder}><span className="menu-lines" aria-hidden="true"><i /><i /><i /></span><b>Record</b></button>
      </header>
      <main className="page">
        <Outlet />
      </main>
      <nav className="mobile-nav" aria-label="Mobile navigation">
        {primaryLinks.slice(0, 4).map((link) => <NavLink key={link.to} to={link.to}><span aria-hidden="true">{link.label.charAt(0)}</span>{link.label}</NavLink>)}
        <details ref={mobileMenu} onKeyDown={closeMenuOnEscape}>
          <summary><span aria-hidden="true">+</span>More</summary>
          <div>
            <NavLink to="/settings" onClick={closeDetails}>Settings</NavLink>
            <a href="https://solve.anthonyngene.com/" onClick={closeDetails}>Study <span aria-hidden="true">↗</span></a>
          </div>
        </details>
      </nav>
    </div>
  );
}
