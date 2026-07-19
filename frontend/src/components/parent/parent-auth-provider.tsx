"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  type ReactNode,
} from "react";
import { useAuth } from "@/components/auth/auth-provider";
import { AuthApiError } from "@/lib/auth";
import { ParentApiError } from "@/lib/parent-api";

type ParentAuthStatus = "authenticated" | "anonymous";

interface ParentAuthContextValue {
  status: ParentAuthStatus;
  token: string | null;
  isHydrating: boolean;
  isAuthenticated: boolean;
  login: (email: string, password: string, tenantSlug: string) => Promise<void>;
  logout: () => void;
}

const ParentAuthContext = createContext<ParentAuthContextValue | undefined>(undefined);

export function ParentAuthProvider({ children }: { children: ReactNode }) {
  return <ParentAuthBridge>{children}</ParentAuthBridge>;
}

function ParentAuthBridge({ children }: { children: ReactNode }) {
  const auth = useAuth();

  const login = useCallback(async (email: string, password: string, tenantSlug: string) => {
    try {
      await auth.login(email, password, tenantSlug || auth.tenantSlug);
    } catch (error) {
      if (error instanceof AuthApiError) {
        throw new ParentApiError(error.status, error.message, error.body);
      }
      if (error instanceof ParentApiError) {
        throw error;
      }
      throw new ParentApiError(500, "Authentication failed.", null);
    }
  }, [auth]);

  const status: ParentAuthStatus = auth.token ? "authenticated" : "anonymous";

  const value = useMemo<ParentAuthContextValue>(
    () => ({
      status,
      token: auth.token,
      isHydrating: auth.isHydrating,
      isAuthenticated: status === "authenticated" && Boolean(auth.token),
      login,
      logout: auth.logout,
    }),
    [status, auth.token, auth.isHydrating, login, auth.logout],
  );

  return <ParentAuthContext.Provider value={value}>{children}</ParentAuthContext.Provider>;
}

export function useParentAuth(): ParentAuthContextValue {
  const context = useContext(ParentAuthContext);
  const shared = useAuth();
  if (context) {
    return context;
  }

  return {
    status: shared.token ? "authenticated" : "anonymous",
    token: shared.token,
    isHydrating: shared.isHydrating,
    isAuthenticated: Boolean(shared.token),
    login: async (email: string, password: string, tenantSlug: string) => {
      try {
        await shared.login(email, password, tenantSlug || shared.tenantSlug);
      } catch (error) {
        if (error instanceof AuthApiError) {
          throw new ParentApiError(error.status, error.message, error.body);
        }
        if (error instanceof ParentApiError) {
          throw error;
        }
        throw new ParentApiError(500, "Authentication failed.", null);
      }
    },
    logout: shared.logout,
  };
}
