import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useState } from "react";
import { api } from "../../api/client";

export function StravaInclineControl({ activityId, incline }: { activityId: number; incline: number | null }) {
  const queryClient = useQueryClient();
  const inputId = useId();
  const [value, setValue] = useState(incline == null ? "" : String(incline));
  useEffect(() => setValue(incline == null ? "" : String(incline)), [incline]);
  const save = useMutation({
    mutationFn: () => api(`/integrations/strava/activities/${activityId}/incline`, {
      method: "PATCH",
      body: JSON.stringify({ incline_percent: value.trim() === "" ? null : Number(value) }),
    }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["history"] }),
        queryClient.invalidateQueries({ queryKey: ["today"] }),
        queryClient.invalidateQueries({ queryKey: ["today-details"] }),
        queryClient.invalidateQueries({ queryKey: ["coach-feedback"] }),
      ]);
    },
  });
  const valid = value.trim() === "" || (Number.isFinite(Number(value)) && Number(value) >= 0 && Number(value) <= 40);
  return <details className="strava-incline">
    <summary>{incline == null ? "Record treadmill incline" : `Edit treadmill incline (${incline}%)`}</summary>
    <form onSubmit={(event) => { event.preventDefault(); if (valid) save.mutate(); }}>
      <label htmlFor={inputId}>Actual treadmill incline (%)<input id={inputId} type="number" min="0" max="40" step="any" inputMode="decimal" value={value} disabled={save.isPending} onChange={(event) => { setValue(event.target.value); save.reset(); }} /></label>
      <small>Enter the incline you ran at. Leave blank to clear it. This updates your record and suggested Strava name; elevation gain on Strava stays unchanged.</small>
      <button type="submit" className="quiet small" disabled={save.isPending || !valid}>{save.isPending ? "Saving..." : "Save incline"}</button>
    </form>
    {save.error && <p className="error" role="alert">{save.error.message}</p>}
    {save.isSuccess && <p className="success" role="status">Treadmill incline saved.</p>}
  </details>;
}
