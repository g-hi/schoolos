interface CardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  color?: "indigo" | "green" | "amber" | "red" | "gray";
}

const colors = {
  indigo: "bg-indigo-50 text-indigo-700 border-indigo-200",
  green: "bg-green-50 text-green-700 border-green-200",
  amber: "bg-amber-50 text-amber-700 border-amber-200",
  red: "bg-red-50 text-red-700 border-red-200",
  gray: "bg-gray-50 text-gray-700 border-gray-200",
};

export default function StatCard({ title, value, subtitle, color = "indigo" }: CardProps) {
  return (
    <div className={`rounded-xl border p-5 ${colors[color]}`}>
      <p className="text-sm font-medium opacity-80">{title}</p>
      <p className="text-3xl font-bold mt-1">{value}</p>
      {subtitle && <p className="text-xs mt-1 opacity-60">{subtitle}</p>}
    </div>
  );
}
