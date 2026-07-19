"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import LoginPanel from "@/components/auth/login-panel";
import { routeForRole } from "@/lib/auth";
import { useAuth } from "@/components/auth/auth-provider";

export default function LoginPage() {
  const router = useRouter();
  const { isHydrating, isAuthenticated, user } = useAuth();

  useEffect(() => {
    if (isHydrating || !isAuthenticated) return;
    const destination = routeForRole(user?.role);
    if (destination) {
      router.replace(destination);
    }
  }, [isHydrating, isAuthenticated, user?.role, router]);

  if (isHydrating) {
    return <p className="text-sm text-gray-600">Loading session...</p>;
  }

  return <LoginPanel />;
}
