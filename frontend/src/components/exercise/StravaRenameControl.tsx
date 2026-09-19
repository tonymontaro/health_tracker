import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { NavLink } from "react-router-dom";
import { api } from "../../api/client";
import type { EntryStatus } from "../../api/types";

export function StravaRenameControl({ activity }: { activity: NonNullable<EntryStatus["strava_activity"]> }) {
  const queryClient = useQueryClient();
  const inputId = useId();
  const [name, setName] = useState(activity.recommended_name);
  const rename = useMutation({
    mutationFn: (customName: string | null) => api<{ name: string }>(`/integrations/strava/activities/${activity.activity_id}/name`, {
      method: "PUT",
      body: JSON.stringify({ name: customName }),
    }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["history"] }),
        queryClient.invalidateQueries({ queryKey: ["today"] }),
        queryClient.invalidateQueries({ queryKey: ["today-details"] }),
        queryClient.invalidateQueries({ queryKey: ["strava"] }),
      ]);
    },
  });
  return <details className="strava-rename">
    <summary>Rename on Strava</summary>
    <p className="strava-name-suggestion">Suggested: <strong>{activity.recommended_name}</strong></p>
    {!activity.can_rename && <p><NavLink to="/settings">Reconnect Strava in Settings</NavLink> to allow activity renaming.</p>}
    <button type="button" className="quiet small" disabled={!activity.can_rename || rename.isPending} onClick={() => rename.mutate(null)}>{rename.isPending ? "Renaming..." : "Use suggested name"}</button>
    <details className="strava-custom-name">
      <summary>Use a custom name</summary>
      <form onSubmit={(event) => { event.preventDefault(); if (name.trim()) rename.mutate(name.trim()); }}>
        <label htmlFor={inputId}>Activity name<input id={inputId} type="text" required maxLength={300} value={name} disabled={!activity.can_rename || rename.isPending} onChange={(event) => { setName(event.target.value); rename.reset(); }} /></label>
        <button className="primary small" disabled={!activity.can_rename || rename.isPending || !name.trim()}>{rename.isPending ? "Renaming..." : "Save name to Strava"}</button>
      </form>
    </details>
    {rename.error && <p className="error" role="alert">{rename.error.message}</p>}
    {rename.isSuccess && <p className="success" role="status">Renamed on Strava to {rename.data.name}.</p>}
  </details>;
}
