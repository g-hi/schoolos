import TeacherReportDetailPage from "@/components/reports/teacher-report-detail-page";
import RoleGuard from "@/components/auth/role-guard";

export default async function TeacherReportDetailRoute({ params }: { params: Promise<{ reportId: string }> }) {
  const { reportId } = await params;
  return (
    <RoleGuard
      allowedRoles={["teacher"]}
      forbiddenMessage="Permission denied. This route is only available to teacher accounts."
    >
      <TeacherReportDetailPage reportId={reportId} />
    </RoleGuard>
  );
}
