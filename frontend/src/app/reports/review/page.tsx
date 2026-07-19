import ReviewQueuePage from "@/components/reports/review-queue-page";
import RoleGuard from "@/components/auth/role-guard";

export default function ReportsReviewRoute() {
  return (
    <RoleGuard
      allowedRoles={["principal", "school_admin"]}
      forbiddenMessage="Permission denied. Leadership access is required for report review routes."
    >
      <ReviewQueuePage />
    </RoleGuard>
  );
}
