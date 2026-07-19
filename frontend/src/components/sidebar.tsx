"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/components/auth/auth-provider";
import { isLeadershipRole } from "@/lib/auth";

const principalNav = [
  { href: "/", label: "Dashboard", icon: "📊" },
  { href: "/reports/review", label: "Weekly Reports", icon: "🗂️" },
  { href: "/timetable", label: "Timetable", icon: "📅" },
  { href: "/substitution", label: "Substitution", icon: "🔄" },
  { href: "/duties", label: "Duty Schedule", icon: "🛡️" },
  { href: "/communication", label: "Communication", icon: "💬" },
  { href: "/pickup", label: "Pickup", icon: "🚗" },
  { href: "/data", label: "Data Upload", icon: "📁" },
  { href: "/social", label: "Social Media", icon: "📱" },
  { href: "/audit", label: "Audit Trail", icon: "🔍" },
];

const teacherNav = [
  { href: "/teacher", label: "Dashboard", icon: "📊" },
  { href: "/teacher/reports", label: "Weekly Reports", icon: "🗂️" },
  { href: "/teacher/my-classes", label: "My Classes", icon: "🏫" },
  { href: "/teacher/lesson-planning", label: "Lesson Planning", icon: "📝" },
  { href: "/teacher/assessment-studio", label: "Assessment Studio", icon: "🧠" },
  { href: "/teacher/exam-marking", label: "Exam Marking", icon: "✅" },
  { href: "/teacher/student-insights", label: "Student Insights", icon: "📈" },
  { href: "/teacher/student-pickup", label: "Student Pickup", icon: "🚗" },
  { href: "/teacher/parent-communication", label: "Parent Communication", icon: "💬" },
  { href: "/teacher/resources", label: "Resources", icon: "📚" },
  { href: "/teacher/settings", label: "Settings", icon: "⚙️" },
];

const parentNav = [
  { href: "/parent", label: "Family Hub", icon: "🏠" },
  { href: "/parent/dashboard", label: "Dashboard", icon: "📊" },
  { href: "/parent/reports", label: "Weekly Reports", icon: "🗂️" },
  { href: "/parent/family", label: "Family Timeline", icon: "🕒" },
  { href: "/parent/assistant", label: "Parent Assistant", icon: "🤖" },
];

export default function Sidebar() {
  const pathname = usePathname();
  const { user, logout } = useAuth();
  const role = user?.role;

  const nav = role === "parent" ? parentNav : role === "teacher" ? teacherNav : isLeadershipRole(role) ? principalNav : [];
  const roleBadge = role === "parent" ? "PA" : role === "teacher" ? "T" : "P";
  const roleLabel = role === "parent" ? "Parent" : role === "teacher" ? "Teacher" : isLeadershipRole(role) ? "Leadership" : "Unknown";
  const roleDetail = role === "parent" ? "Family" : role === "teacher" ? "Portal" : isLeadershipRole(role) ? "Admin" : "Access";

  return (
    <aside className="w-64 bg-white border-r border-gray-200 flex flex-col">
      <div className="p-6 border-b border-gray-200">
        <h1 className="text-xl font-bold text-indigo-600">SchoolOS</h1>
        <p className="text-xs text-gray-500 mt-1">Greenwood International</p>
      </div>
      <nav className="flex-1 p-4 space-y-1">
        {nav.map((item) => {
          const active =
            item.href === "/"
              ? pathname === "/"
              : pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                active
                  ? "bg-indigo-50 text-indigo-700"
                  : "text-gray-600 hover:bg-gray-100 hover:text-gray-900"
              }`}
            >
              <span className="text-lg">{item.icon}</span>
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="p-4 border-t border-gray-200">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-full bg-indigo-100 flex items-center justify-center text-indigo-600 font-bold text-sm">
              {roleBadge}
            </div>
            <div>
              <p className="text-sm font-medium">{roleLabel}</p>
              <p className="text-xs text-gray-500">{roleDetail}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={logout}
            className="rounded-lg border border-gray-300 px-2 py-1 text-xs font-medium text-gray-700 transition hover:bg-gray-50"
          >
            Sign out
          </button>
        </div>
      </div>
    </aside>
  );
}
