"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { clearParentToken, readParentToken, writeParentToken } from "@/lib/parent-auth";
import {
  ParentApiError,
  loginParent,
  setParentUnauthorizedHandler,
} from "@/lib/parent-api";

type ParentAuthStatus = "authenticated" | "anonymous";

interface ParentAuthContextValue {
  status: ParentAuthStatus;
  token: string | null;
  isHydrating: boolean;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const ParentAuthContext = createContext<ParentAuthContextValue | undefined>(undefined);

export function ParentAuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => readParentToken());

  const logout = useCallback(() => {
    clearParentToken();
    setToken(null);
  }, []);

  useEffect(() => {
    setParentUnauthorizedHandler(logout);
    return () => {
      setParentUnauthorizedHandler(null);
    };
  }, [logout]);

  const login = useCallback(async (email: string, password: string) => {
    const response = await loginParent(email, password);
    if (!response.access_token) {
      throw new ParentApiError(500, "Authentication failed.", null);
    }

    writeParentToken(response.access_token);
    setToken(response.access_token);
  }, []);

  const status: ParentAuthStatus = token ? "authenticated" : "anonymous";

  const value = useMemo<ParentAuthContextValue>(
    () => ({
      status,
      token,
      isHydrating: false,
      isAuthenticated: status === "authenticated" && Boolean(token),
      login,
      logout,
    }),
    [status, token, login, logout],
  );

  return <ParentAuthContext.Provider value={value}>{children}</ParentAuthContext.Provider>;
}

export function useParentAuth(): ParentAuthContextValue {
  const context = useContext(ParentAuthContext);
  if (!context) {
    throw new Error("useParentAuth must be used within ParentAuthProvider.");
  }
  return context;
}
