import ParentReportDetailPage from "@/components/parent/parent-report-detail-page";

export default async function ParentReportDetailRoute({ params }: { params: Promise<{ reportId: string }> }) {
  const { reportId } = await params;
  return <ParentReportDetailPage reportId={reportId} />;
}
