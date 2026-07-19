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
import {
  AuthApiError,
  clearAuthSession,
  getMe,
  login as loginRequest,
  readAccessToken,
  readAuthProfile,
  readTenantSlug,
  writeAccessToken,
  writeAuthProfile,
  writeTenantSlug,
  type AuthProfile,
} from "@/lib/auth";
import { clearParentAssistantSession } from "@/lib/parent-auth";
import { setUnauthorizedHandler as setParentUnauthorizedHandler } from "@/lib/parent-api";
import { setUnauthorizedHandler as setWeeklyReportsUnauthorizedHandler } from "@/lib/weekly-reports-api";

type AuthStatus = "authenticated" | "anonymous";

interface AuthContextValue {
  status: AuthStatus;
  token: string | null;
  user: AuthProfile | null;
  tenantSlug: string;
  isHydrating: boolean;
  isAuthenticated: boolean;
  login: (email: string, password: string, tenantSlug: string) => Promise<AuthProfile>;
  logout: () => void;
  refreshProfile: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => readAccessToken());
  const [tenantSlug, setTenantSlug] = useState<string>(() => readTenantSlug());
  const [user, setUser] = useState<AuthProfile | null>(() => readAuthProfile());
  const [isHydrating, setIsHydrating] = useState<boolean>(() => Boolean(readAccessToken()));

  const logout = useCallback(() => {
    clearParentAssistantSession();
    clearAuthSession();
    setToken(null);
    setUser(null);
    setTenantSlug(readTenantSlug());
  }, []);

  const refreshProfile = useCallback(async () => {
    const currentToken = readAccessToken();
    const currentTenant = readTenantSlug();
    if (!currentToken) {
      setUser(null);
      return;
    }
    const nextProfile = await getMe(currentToken, currentTenant);
    writeAuthProfile(nextProfile);
    setUser(nextProfile);
    setTenantSlug(nextProfile.tenant_slug);
  }, []);

  const login = useCallback(async (email: string, password: string, tenant: string) => {
    const normalizedTenant = tenant.trim().toLowerCase();
    const auth = await loginRequest(email, password, normalizedTenant);
    writeAccessToken(auth.access_token);
    writeTenantSlug(normalizedTenant);
    const profile = await getMe(auth.access_token, normalizedTenant);
    writeAuthProfile(profile);
    setToken(auth.access_token);
    setTenantSlug(profile.tenant_slug);
    setUser(profile);
    return profile;
  }, []);

  useEffect(() => {
    const handleUnauthorized = () => logout();
    setParentUnauthorizedHandler(handleUnauthorized);
    setWeeklyReportsUnauthorizedHandler(handleUnauthorized);
    return () => {
      setParentUnauthorizedHandler(null);
      setWeeklyReportsUnauthorizedHandler(null);
    };
  }, [logout]);

  useEffect(() => {
    const currentToken = readAccessToken();
    const currentTenant = readTenantSlug();
    if (!currentToken) {
      return;
    }

    void getMe(currentToken, currentTenant)
      .then((profile) => {
        writeAuthProfile(profile);
        setUser(profile);
        setTenantSlug(profile.tenant_slug);
      })
      .catch((error) => {
        if (error instanceof AuthApiError && error.status === 401) {
          logout();
        }
      })
      .finally(() => {
        setIsHydrating(false);
      });
  }, [logout]);

  const status: AuthStatus = token ? "authenticated" : "anonymous";

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      token,
      user,
      tenantSlug,
      isHydrating,
      isAuthenticated: Boolean(token && user),
      login,
      logout,
      refreshProfile,
    }),
    [status, token, user, tenantSlug, isHydrating, login, logout, refreshProfile],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider.");
  }
  return context;
}
