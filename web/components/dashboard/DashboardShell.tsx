"use client";

import { useQuery, Authenticated, AuthLoading } from "convex/react";
import { api } from "@cp/api";
import { TierCard } from "@/components/dashboard/TierCard";
import { UsagePanel } from "@/components/dashboard/UsagePanel";
import { ConnectionsPanel } from "@/components/dashboard/ConnectionsPanel";
import { SignOutButton } from "@/components/dashboard/SignOutButton";

export function DashboardShell() {
  return (
    <main id="main" className="mx-auto min-h-dvh w-full max-w-5xl px-5 py-6 sm:px-8">
      <TopBar />

      {/* Polite live region announces loading/loaded state to screen readers (item 13).
          Skeletons are aria-hidden so they're never perceived directly. */}
      <AuthLoading>
        <div role="status" aria-live="polite" aria-atomic="true" className="sr-only">
          loading dashboard…
        </div>
        <DashboardSkeleton />
      </AuthLoading>

      <Authenticated>
        {/* SR-only page heading — document has exactly one h1 (item 5). */}
        <h1 className="sr-only">dashboard</h1>

        {/* Screen readers hear this once data arrives (item 13). */}
        <div role="status" aria-live="polite" aria-atomic="true" className="sr-only">
          dashboard loaded
        </div>

        {/* three equal, equal-height cards: symmetric 1→2→3 columns, items-stretch
            so plan/usage/channels share one height. */}
        <section className="mt-8 grid grid-cols-1 items-stretch gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <TierCard />
          <UsagePanel />
          <ConnectionsPanel />
        </section>
      </Authenticated>
    </main>
  );
}

function TopBar() {
  return (
    <header className="flex items-center justify-between gap-4 border-b border-border pb-4">
      <div className="flex items-center gap-3">
        <span className="font-mono text-lg font-medium text-lime">Amyris</span>
        <span className="hidden text-faint sm:inline" aria-hidden>
          /
        </span>
        <span className="hidden font-mono text-sm text-muted sm:inline">
          dashboard
        </span>
      </div>

      <div className="flex items-center gap-3">
        {/* currentUser is an auth-gated query (it throws when unauthenticated).
            Only mount it while authenticated so signing out unmounts it cleanly
            instead of firing an uncaught "unauthenticated" error mid-transition. */}
        <Authenticated>
          <UserEmail />
        </Authenticated>
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

  const label = user?.email ?? user?.phone ?? user?.displayName ?? user?.name ?? null;
  if (!label) return null;

  return (
    <span className="hidden max-w-[12rem] truncate font-mono text-sm text-muted sm:inline">
      {label}
    </span>
  );
}

function DashboardSkeleton() {
  // aria-hidden: pure visual skeleton, never perceived (item 13)
  return (
    <section
      className="mt-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3"
      aria-hidden="true"
    >
      <div className="h-56 rounded-[var(--radius-lg)] border border-border bg-surface" />
      <div className="h-56 rounded-[var(--radius-lg)] border border-border bg-surface" />
      <div className="h-56 rounded-[var(--radius-lg)] border border-border bg-surface" />
    </section>
  );
}
