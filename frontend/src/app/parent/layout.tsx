import type { ReactNode } from "react";
import { ParentAuthProvider } from "@/components/parent/parent-auth-provider";

export default function ParentLayout({ children }: { children: ReactNode }) {
  return (
    <ParentAuthProvider>
      <div className="mx-auto w-full max-w-7xl space-y-6 px-1 sm:px-2">{children}</div>
    </ParentAuthProvider>
  );
}
