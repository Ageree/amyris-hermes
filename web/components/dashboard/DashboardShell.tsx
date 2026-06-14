"use client";

import { useQuery, Authenticated, AuthLoading } from "convex/react";
import { api } from "@cp/api";
import { TierCard } from "@/components/dashboard/TierCard";
import { UsagePanel } from "@/components/dashboard/UsagePanel";
import { ConnectionsPanel } from "@/components/dashboard/ConnectionsPanel";
import { SignOutButton } from "@/components/dashboard/SignOutButton";

export function DashboardShell() {
  return (
    <main className="mx-auto min-h-dvh w-full max-w-5xl px-5 py-6 sm:px-8">
      <TopBar />

      {/* the unauthed edge is handled by middleware (redirect to /signin). while
          auth resolves we show a calm shell; we never render data unauthed. */}
      <AuthLoading>
        <DashboardSkeleton />
      </AuthLoading>

      <Authenticated>
        <section className="mt-8 grid grid-cols-1 gap-4 lg:grid-cols-3">
          {/* tier + usage stack on the left; connections take the right column on
              wide screens, full width when stacked. */}
          <div className="flex flex-col gap-4 lg:col-span-2">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <TierCard />
              <UsagePanel />
            </div>
          </div>
          <div className="lg:col-span-1">
            <ConnectionsPanel />
          </div>
        </section>
      </Authenticated>
    </main>
  );
}

function TopBar() {
  return (
    <header className="flex items-center justify-between gap-4 border-b border-border pb-4">
      <div className="flex items-center gap-3">
        <span className="font-mono text-lg font-medium text-lime">hermes</span>
        <span className="hidden text-faint sm:inline" aria-hidden>
          /
        </span>
        <span className="hidden font-mono text-sm text-muted sm:inline">
          dashboard
        </span>
      </div>

      <div className="flex items-center gap-3">
        <UserEmail />
        <SignOutButton />
      </div>
    </header>
  );
}

function UserEmail() {
  const user = useQuery(api.app.account.currentUser);

  if (user === undefined) {
    return (
      <span
        className="hidden h-4 w-32 animate-pulse rounded bg-surface-2 sm:inline-block"
        aria-hidden
      />
    );
  }

  const label = user?.email ?? user?.displayName ?? user?.name ?? null;
  if (!label) return null;

  return (
    <span className="hidden max-w-[12rem] truncate font-mono text-sm text-muted sm:inline">
      {label}
    </span>
  );
}

function DashboardSkeleton() {
  return (
    <section
      className="mt-8 grid grid-cols-1 gap-4 lg:grid-cols-3"
      aria-hidden
      aria-busy="true"
    >
      <div className="flex flex-col gap-4 lg:col-span-2">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="h-44 rounded-[var(--radius)] border border-border bg-surface" />
          <div className="h-44 rounded-[var(--radius)] border border-border bg-surface" />
        </div>
      </div>
      <div className="h-64 rounded-[var(--radius)] border border-border bg-surface lg:col-span-1" />
    </section>
  );
}
