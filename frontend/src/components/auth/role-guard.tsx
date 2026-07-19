"use client";

import type { ReactNode } from "react";
import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/components/auth/auth-provider";

interface RoleGuardProps {
  allowedRoles: string[];
  children: ReactNode;
  forbiddenMessage: string;
}

export default function RoleGuard({ allowedRoles, children, forbiddenMessage }: RoleGuardProps) {
  const router = useRouter();
  const pathname = usePathname();
  const { isHydrating, isAuthenticated, user } = useAuth();

  useEffect(() => {
    if (isHydrating || pathname === "/login") return;
    if (!isAuthenticated) {
      router.replace("/login");
    }
  }, [isHydrating, isAuthenticated, pathname, router]);

  if (isHydrating) {
    return <p className="text-sm text-gray-600">Loading session...</p>;
  }

  if (!isAuthenticated) {
    return null;
  }

  if (!user || !user.is_active) {
    return (
      <section className="rounded-xl border border-red-200 bg-red-50 p-4 text-red-700">
        Your account is inactive. Please contact your administrator.
      </section>
    );
  }

  if (!allowedRoles.includes(user.role)) {
    return (
      <section className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-amber-800" role="alert">
        {forbiddenMessage}
      </section>
    );
  }

  return <>{children}</>;
}
