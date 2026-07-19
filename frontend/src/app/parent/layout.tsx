import type { ReactNode } from "react";

export default function ParentLayout({ children }: { children: ReactNode }) {
  return <div className="mx-auto w-full max-w-7xl space-y-6 px-1 sm:px-2">{children}</div>;
}
