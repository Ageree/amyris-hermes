import { DashboardShell } from "@/components/dashboard/DashboardShell";

// auth-gated by middleware (unauthed → /signin). this server component renders
// the client shell, which drives all the live convex queries.
export default function DashboardPage() {
  return <DashboardShell />;
}
