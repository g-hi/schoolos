import ReviewDetailPage from "@/components/reports/review-detail-page";
import RoleGuard from "@/components/auth/role-guard";

export default async function ReportReviewDetailRoute({ params }: { params: Promise<{ reportId: string }> }) {
  const { reportId } = await params;
  return (
    <RoleGuard
      allowedRoles={["principal", "school_admin"]}
      forbiddenMessage="Permission denied. Leadership access is required for report review routes."
    >
      <ReviewDetailPage reportId={reportId} />
    </RoleGuard>
  );
}
