import { NavLink, Outlet } from "react-router-dom";

export function Layout() {
  return (
    <div className="app-shell">
      <header className="topbar">
        <NavLink className="brand" to="/today">
          <span className="brand-mark">HA</span>
          <span>Health Autopilot</span>
        </NavLink>
        <nav aria-label="Primary navigation">
          <NavLink to="/today">Today</NavLink>
          <NavLink to="/history">History</NavLink>
          <NavLink to="/shopping">Shopping</NavLink>
          <NavLink to="/settings">Settings</NavLink>
        </nav>
      </header>
      <main className="page"><Outlet /></main>
    </div>
  );
}

