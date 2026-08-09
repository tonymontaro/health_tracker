import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { api, setCsrf } from "../api/client";
import { AuthContext, type Session } from "./auth";

export function AuthProvider({ children }: { children: ReactNode }) {
  const query = useQuery({
    queryKey: ["session"],
    queryFn: async () => {
      const session = await api<Session>("/auth/session");
      setCsrf(session.csrf_token);
      return session;
    },
    retry: false,
  });
  return (
    <AuthContext.Provider value={{ session: query.data, loading: query.isLoading, refresh: query.refetch }}>
      {children}
    </AuthContext.Provider>
  );
}
