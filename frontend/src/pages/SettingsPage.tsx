import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { api, setCsrf } from "../api/client";
import type { Equipment, Profile, StravaIntegration } from "../api/types";
import { useAuth } from "../components/auth";
import { ConfirmDialog } from "../components/field-notes/ConfirmDialog";

function commaList(value: string): string[] {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

function RuntimeDetails({ data, loading, error }: { data?: Record<string, string | boolean | number>; loading: boolean; error: Error | null }) {
  const dialog = useRef<HTMLDialogElement>(null);
  return <>
    <button className="quiet" type="button" onClick={() => dialog.current?.showModal()}>Runtime details</button>
    <dialog className="detail-sheet" ref={dialog} aria-labelledby="runtime-details-title">
      <form method="dialog"><button className="sheet-close">Close ×</button></form>
      <p className="eyebrow">Settings / Technical detail</p>
      <h2 id="runtime-details-title">Runtime details</h2>
      {loading && <p role="status">Loading runtime details...</p>}
      {error && <p className="error" role="alert">{error.message}</p>}
      {!loading && !error && Object.keys(data ?? {}).length === 0 && <p>No runtime details are available.</p>}
      <div className="rule-list">{Object.entries(data ?? {}).map(([key, value]) => <div key={key}><span>{key.replaceAll("_", " ")}</span><strong>{String(value)}</strong></div>)}</div>
    </dialog>
  </>;
}

export function SettingsPage() {
  const queryClient = useQueryClient();
  const { session } = useAuth();
  const profile = useQuery({ queryKey: ["profile"], queryFn: () => api<Profile>("/profile") });
  const equipment = useQuery({ queryKey: ["equipment"], queryFn: () => api<Equipment[]>("/equipment") });
  const runtime = useQuery({ queryKey: ["runtime-settings"], queryFn: () => api<Record<string, string | boolean | number>>("/settings") });
  const strava = useQuery({ queryKey: ["strava"], queryFn: () => api<StravaIntegration>("/integrations/strava") });
  const [form, setForm] = useState<Partial<Profile>>({});
  const [createdToken, setCreatedToken] = useState("");
  const [confirmDisconnect, setConfirmDisconnect] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmedPassword, setConfirmedPassword] = useState("");
  useEffect(() => { if (profile.data) setForm(profile.data); }, [profile.data]);
  const save = useMutation({ mutationFn: () => api<Profile>("/profile", { method: "PATCH", body: JSON.stringify(form) }), onSuccess: () => queryClient.invalidateQueries({ queryKey: ["profile"] }) });
  const equipmentUpdate = useMutation({ mutationFn: ({ id, available }: { id: string; available: boolean }) => api<Equipment>(`/equipment/${id}`, { method: "PATCH", body: JSON.stringify({ available }) }), onSuccess: () => queryClient.invalidateQueries({ queryKey: ["equipment"] }) });
  const token = useMutation({ mutationFn: () => api<{ token: string }>("/auth/tokens?name=Chrome%20extension", { method: "POST" }), onSuccess: (data) => setCreatedToken(data.token) });
  const connectStrava = useMutation({ mutationFn: () => api<{ authorization_url: string }>("/integrations/strava/connect", { method: "POST" }), onSuccess: (data) => window.location.assign(data.authorization_url) });
  const syncStrava = useMutation({ mutationFn: () => api("/integrations/strava/sync", { method: "POST" }), onSuccess: async () => { await Promise.all([queryClient.invalidateQueries({ queryKey: ["strava"] }), queryClient.invalidateQueries({ queryKey: ["today"] }), queryClient.invalidateQueries({ queryKey: ["history"] })]); } });
  const disconnectStrava = useMutation({ mutationFn: () => api("/integrations/strava", { method: "DELETE" }), onSuccess: async () => { await Promise.all([queryClient.invalidateQueries({ queryKey: ["strava"] }), queryClient.invalidateQueries({ queryKey: ["today"] }), queryClient.invalidateQueries({ queryKey: ["history"] })]); } });
  const changePassword = useMutation({
    mutationFn: () => api<void>("/auth/password", { method: "POST", body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }) }),
    onSuccess: () => {
      setCurrentPassword("");
      setNewPassword("");
      setConfirmedPassword("");
    },
  });
  const logout = useMutation({
    mutationFn: () => api<void>("/auth/logout", { method: "POST" }),
    onSuccess: () => {
      setCsrf("");
      queryClient.clear();
      window.location.replace("/login");
    },
  });
  function submit(event: FormEvent) { event.preventDefault(); save.mutate(); }
  function submitPassword(event: FormEvent) {
    event.preventDefault();
    if (newPassword === confirmedPassword && newPassword !== currentPassword) changePassword.mutate();
  }
  if (profile.isLoading) return <div className="loading" role="status">Loading settings...</div>;
  if (profile.error) return <div className="error-panel" role="alert"><h1>Settings are unavailable</h1><p>{profile.error.message}</p></div>;
  if (!profile.data) return <div className="error-panel" role="alert"><h1>Settings are unavailable</h1></div>;
  const strength = form.strength_capacity_json ?? {};
  const bench = (strength.bench_press as Record<string, unknown> | undefined) ?? {};
  const pullUp = (strength.strict_pull_up as Record<string, unknown> | undefined) ?? {};
  const endurance = form.endurance_capacity_json ?? {};
  const running = (endurance.running as Record<string, unknown> | undefined) ?? {};
  const runGoal = (running.goal_distance_km as number[] | undefined) ?? [8, 12];
  const nutrition = form.nutrition_preferences ?? {};
  const proteinRange = (nutrition.protein_range_g as number[] | undefined) ?? [145, 170];
  const passwordMismatch = confirmedPassword.length > 0 && newPassword !== confirmedPassword;
  const passwordUnchanged = newPassword.length > 0 && newPassword === currentPassword;
  const passwordReady = currentPassword.length >= 8 && newPassword.length >= 12 && newPassword === confirmedPassword && !passwordUnchanged;
  return <><header className="page-header"><div><p className="eyebrow">Your constraints and preferences</p><h1>Settings</h1></div><p className="page-deck">The rules, equipment, capacity, and integrations that shape each daily recommendation.</p></header>
    <form className="settings-grid" onSubmit={submit}><section className="card"><p className="eyebrow">Profile</p><div className="form-grid"><label>Location<input value={form.location ?? ""} onChange={(event) => setForm({ ...form, location: event.target.value })} /></label><label>Timezone<input value={form.timezone ?? ""} onChange={(event) => setForm({ ...form, timezone: event.target.value })} /></label><label>Weight kg<input type="number" value={form.weight_kg ?? ""} onChange={(event) => setForm({ ...form, weight_kg: Number(event.target.value) })} /></label><label>Height cm<input type="number" value={form.height_cm ?? ""} onChange={(event) => setForm({ ...form, height_cm: Number(event.target.value) })} /></label><label>Age, optional<input type="number" value={form.age ?? ""} onChange={(event) => setForm({ ...form, age: Number(event.target.value) || null })} /></label><label>Sex, optional<input value={form.sex ?? ""} onChange={(event) => setForm({ ...form, sex: event.target.value || null })} /></label></div><label>Primary training goal<textarea value={form.primary_training_goal ?? ""} onChange={(event) => setForm({ ...form, primary_training_goal: event.target.value })} /></label><label>Current target goal<textarea placeholder="Example: Morat–Fribourg, 17.17 km with 335 m ascent, sub 1:35 on 4 October 2026" value={form.current_target_goal ?? ""} onChange={(event) => setForm({ ...form, current_target_goal: event.target.value || null })} /><small>This goal and recent performance evidence are included in every AI planning and coaching context.</small></label><label>Body-composition direction<textarea value={form.body_composition_goal ?? ""} onChange={(event) => setForm({ ...form, body_composition_goal: event.target.value || null })} /></label><button className="primary" disabled={save.isPending}>Save settings</button>{save.isSuccess && <span className="success">Saved</span>}{save.error && <p className="error">{save.error.message}</p>}</section>
      <section className="card"><p className="eyebrow">Planning rules</p><div className="form-grid"><label>Maximum main meals<input type="number" min="1" max="2" value={form.max_main_meals_per_day ?? 2} onChange={(event) => setForm({ ...form, max_main_meals_per_day: Number(event.target.value) })} /></label><label>Preferred main meals<input type="number" min="1" max="2" value={form.preferred_main_meals_per_day ?? 2} onChange={(event) => setForm({ ...form, preferred_main_meals_per_day: Number(event.target.value) })} /></label><label>Maximum exercises<input type="number" min="1" max="3" value={form.max_exercises_per_day ?? 3} onChange={(event) => setForm({ ...form, max_exercises_per_day: Number(event.target.value) })} /></label><label>Thursday commute minutes<input type="number" min="0" value={Number(nutrition.thursday_commute_minutes ?? 180)} onChange={(event) => setForm({ ...form, nutrition_preferences: { ...nutrition, thursday_commute_minutes: Number(event.target.value) } })} /></label></div><label>Gym days, comma separated<input value={(form.gym_days ?? []).join(", ")} onChange={(event) => setForm({ ...form, gym_days: commaList(event.target.value) })} /></label><label>Office days, comma separated<input value={(form.office_days ?? []).join(", ")} onChange={(event) => setForm({ ...form, office_days: commaList(event.target.value) })} /></label><label>Excluded exercises, comma separated<input value={(form.excluded_exercises ?? []).join(", ")} onChange={(event) => setForm({ ...form, excluded_exercises: commaList(event.target.value) })} /></label><label>Allergies, comma separated<input value={(form.allergies ?? []).join(", ")} onChange={(event) => setForm({ ...form, allergies: commaList(event.target.value) })} /></label><label>Medical constraints, comma separated<input value={(form.medical_constraints ?? []).join(", ")} onChange={(event) => setForm({ ...form, medical_constraints: commaList(event.target.value) })} /></label></section>
      <section className="card"><p className="eyebrow">Current capacity</p><div className="form-grid"><label>Bench press load kg<input type="number" min="0" value={Number(bench.load_kg ?? 100)} onChange={(event) => setForm({ ...form, strength_capacity_json: { ...strength, bench_press: { ...bench, load_kg: Number(event.target.value) } } })} /></label><label>Strict pull-ups<input value={String(pullUp.reps ?? ">10")} onChange={(event) => setForm({ ...form, strength_capacity_json: { ...strength, strict_pull_up: { ...pullUp, reps: event.target.value } } })} /></label><label>Running goal minimum km<input type="number" min="0" value={runGoal[0]} onChange={(event) => setForm({ ...form, endurance_capacity_json: { ...endurance, running: { ...running, goal_distance_km: [Number(event.target.value), runGoal[1]] } } })} /></label><label>Running goal maximum km<input type="number" min="0" value={runGoal[1]} onChange={(event) => setForm({ ...form, endurance_capacity_json: { ...endurance, running: { ...running, goal_distance_km: [runGoal[0], Number(event.target.value)] } } })} /></label><label>Cycling FTP watts, optional<input type="number" min="0" value={Number(endurance.cycling_ftp_watts ?? 0) || ""} onChange={(event) => setForm({ ...form, endurance_capacity_json: { ...endurance, cycling_ftp_watts: Number(event.target.value) || null } })} /></label><label>Protein target minimum g<input type="number" min="0" value={proteinRange[0]} onChange={(event) => setForm({ ...form, nutrition_preferences: { ...nutrition, protein_range_g: [Number(event.target.value), proteinRange[1]] } })} /></label><label>Protein target maximum g<input type="number" min="0" value={proteinRange[1]} onChange={(event) => setForm({ ...form, nutrition_preferences: { ...nutrition, protein_range_g: [proteinRange[0], Number(event.target.value)] } })} /></label></div></section>
      <section className="card"><p className="eyebrow">Available equipment</p>{equipment.data?.map((item) => <label className="equipment-row" key={item.id}><input type="checkbox" checked={item.available} onChange={(event) => equipmentUpdate.mutate({ id: item.id, available: event.target.checked })} />{item.name}</label>)}</section>
      <section className="card"><p className="eyebrow">Recommended kitchen additions</p>{(form.kitchen_equipment_json ?? []).map((item) => <label className="equipment-row" key={item.name}><input type="checkbox" checked={item.owned === true} onChange={(event) => setForm({ ...form, kitchen_equipment_json: form.kitchen_equipment_json?.map((candidate) => candidate.name === item.name ? { ...candidate, owned: event.target.checked } : candidate) })} />{item.name}</label>)}</section>
      <section className="card"><p className="eyebrow">Integrations</p><h3>Strava</h3>{strava.data?.connected ? <div className="integration-panel"><p><strong>{strava.data.athlete?.name || "Connected athlete"}</strong></p><small>{strava.data.activity_count} activities imported{strava.data.last_synced_at ? ` · Last synced ${new Date(strava.data.last_synced_at).toLocaleString()}` : ""}</small><div className="actions"><button type="button" className="quiet" disabled={syncStrava.isPending} onClick={() => syncStrava.mutate()}>{syncStrava.isPending ? "Syncing..." : "Sync now"}</button><button type="button" className="quiet" disabled={disconnectStrava.isPending} onClick={() => { disconnectStrava.reset(); setConfirmDisconnect(true); }}>Disconnect</button></div></div> : <div className="integration-panel"><p>Import activities recorded by your watch through Strava and match them to the day's recommendations.</p><button type="button" className="primary" disabled={!strava.data?.configured || connectStrava.isPending} onClick={() => connectStrava.mutate()}>{connectStrava.isPending ? "Opening Strava..." : "Connect with Strava"}</button>{strava.data && !strava.data.configured && <small>Set the Strava client credentials on the backend to enable this connection.</small>}</div>}{strava.data?.last_error && <p className="error">{strava.data.last_error}</p>}{(connectStrava.error || syncStrava.error || disconnectStrava.error) && <p className="error">{connectStrava.error?.message ?? syncStrava.error?.message ?? disconnectStrava.error?.message}</p>}<hr /><h3>Chrome extension token</h3><p>Generate a revocable token and paste it into the extension. It is shown only once.</p><button type="button" className="quiet" onClick={() => token.mutate()}>Generate token</button>{createdToken && <code className="token-output">{createdToken}</code>}<hr /><RuntimeDetails data={runtime.data} loading={runtime.isLoading} error={runtime.error} /></section>
    </form>
    <section className="card account-security-card">
      <div className="account-security-summary">
        <p className="eyebrow">Account and access</p>
        <h2>Security</h2>
        <p>Signed in as <strong>{session?.email ?? "the account owner"}</strong>.</p>
        <button type="button" className="quiet" disabled={logout.isPending} onClick={() => logout.mutate()}>{logout.isPending ? "Logging out..." : "Log out"}</button>
        {logout.error && <p className="error" role="alert">{logout.error.message}</p>}
      </div>
      <form className="password-change-form" onSubmit={submitPassword}>
        <div><p className="eyebrow">Credentials</p><h3>Change password</h3><p id="password-requirements">Use at least 12 characters. Changing it signs out every other browser session.</p></div>
        <label>Current password<input type="password" autoComplete="current-password" minLength={8} maxLength={200} value={currentPassword} onChange={(event) => { changePassword.reset(); setCurrentPassword(event.target.value); }} /></label>
        <div className="form-grid">
          <label>New password<input type="password" autoComplete="new-password" minLength={12} maxLength={200} aria-describedby="password-requirements" value={newPassword} onChange={(event) => { changePassword.reset(); setNewPassword(event.target.value); }} /></label>
          <label>Confirm new password<input type="password" autoComplete="new-password" minLength={12} maxLength={200} value={confirmedPassword} onChange={(event) => { changePassword.reset(); setConfirmedPassword(event.target.value); }} /></label>
        </div>
        {passwordMismatch && <p className="error" role="alert">The new passwords do not match.</p>}
        {passwordUnchanged && <p className="error" role="alert">Choose a password different from the current password.</p>}
        {changePassword.error && <p className="error" role="alert">{changePassword.error.message}</p>}
        {changePassword.isSuccess && <p className="success" role="status">Password changed. Other browser sessions were signed out.</p>}
        <button type="submit" className="primary" disabled={changePassword.isPending || !passwordReady}>{changePassword.isPending ? "Changing password..." : "Change password"}</button>
      </form>
    </section>
    <ConfirmDialog open={confirmDisconnect} title="Disconnect Strava?" description="Imported Strava records and their matches will be removed as part of this existing disconnect action." confirmLabel="Disconnect Strava" pending={disconnectStrava.isPending} error={disconnectStrava.error?.message} onCancel={() => setConfirmDisconnect(false)} onConfirm={() => disconnectStrava.mutate(undefined, { onSuccess: () => setConfirmDisconnect(false) })} /></>;
}
