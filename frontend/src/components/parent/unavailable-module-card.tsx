import { ModuleUnavailable } from "@/lib/parent-api";

interface UnavailableModuleCardProps {
  label: string;
  state: ModuleUnavailable;
}

export default function UnavailableModuleCard({ label, state }: UnavailableModuleCardProps) {
  return (
    <article className="rounded-2xl border border-gray-200 bg-white p-4">
      <h3 className="text-sm font-semibold text-gray-900">{label}</h3>
      <p className="mt-2 text-sm text-gray-600">{state.reason}</p>
    </article>
  );
}
