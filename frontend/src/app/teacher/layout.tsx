import type { ReactNode } from "react";

export default function TeacherLayout({ children }: { children: ReactNode }) {
  return <div className="max-w-7xl mx-auto space-y-6">{children}</div>;
}
