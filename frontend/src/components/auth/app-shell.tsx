"use client";

import type { ReactNode } from "react";
import { useMemo } from "react";
import dynamic from "next/dynamic";
import { usePathname } from "next/navigation";

const Sidebar = dynamic(() => import("@/components/sidebar"), { ssr: false });
const RoleGuard = dynamic(() => import("@/components/auth/role-guard"), {
  ssr: false,
  loading: () => <p className="text-sm text-gray-600">Loading session...</p>,
});

function getGuardConfig(pathname: string): { allowedRoles: string[]; forbiddenMessage: string } | null {
  if (pathname === "/login") {
    return null;
  }

  if (pathname.startsWith("/parent")) {
    return {
      allowedRoles: ["parent"],
      forbiddenMessage: "Permission denied. This route is only available to parent accounts.",
    };
  }

  if (pathname.startsWith("/teacher")) {
    return {
      allowedRoles: ["teacher"],
      forbiddenMessage: "Permission denied. This route is only available to teacher accounts.",
    };
  }

  if (pathname === "/reports/review" || (pathname.startsWith("/reports/") && pathname.endsWith("/review"))) {
    return {
      allowedRoles: ["principal", "school_admin"],
      forbiddenMessage: "Permission denied. Leadership access is required for report review routes.",
    };
  }

  return {
    allowedRoles: ["principal", "school_admin"],
    forbiddenMessage: "Permission denied. Leadership access is required for this route.",
  };
}

export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const config = useMemo(() => getGuardConfig(pathname || "/"), [pathname]);

  if (!config) {
    return <main className="flex-1 overflow-y-auto p-6">{children}</main>;
  }

  return (
    <>
      <Sidebar />
      <main className="flex-1 overflow-y-auto p-6">
        <RoleGuard allowedRoles={config.allowedRoles} forbiddenMessage={config.forbiddenMessage}>
          {children}
        </RoleGuard>
      </main>
    </>
  );
}
