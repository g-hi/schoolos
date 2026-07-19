import TeacherReportsPage from "@/components/reports/teacher-reports-page";
import RoleGuard from "@/components/auth/role-guard";

export default function TeacherReportsRoute() {
  return (
    <RoleGuard
      allowedRoles={["teacher"]}
      forbiddenMessage="Permission denied. This route is only available to teacher accounts."
    >
      <TeacherReportsPage />
    </RoleGuard>
  );
}
