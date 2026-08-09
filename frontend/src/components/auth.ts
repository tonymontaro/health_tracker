import { createContext, useContext } from "react";

export type Session = { authenticated: boolean; email: string; csrf_token: string };
export type AuthState = { session?: Session; loading: boolean; refresh: () => Promise<unknown> };

export const AuthContext = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}
