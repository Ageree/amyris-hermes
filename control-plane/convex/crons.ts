import { cronJobs } from "convex/server";
import { internal } from "./_generated/api";

const internalAny = internal as any;

// ---------------------------------------------------------------------------
// Scheduled jobs (design §4/§6). Each target is an internalMutation that is
// PAGINATED + self-rescheduling, so a cron tick never exceeds the per-mutation
// read/write limits no matter how many rows are due. More reapers (stale
// "processing", idle instances, stale pairing tokens) land here in M6.
// ---------------------------------------------------------------------------
const crons = cronJobs();

// Reset the rolling 30-day quota window for entitlements whose period has ended.
// checkAndReserve also self-rolls on read; this keeps idle users' dashboards fresh.
crons.interval(
  "roll expired entitlement periods",
  { hours: 1 },
  internal.billing.grant.rollExpiredPeriods,
  {},
);

// Reset rows stuck in "processing" by a worker that crashed mid-flight back to
// "queued" so a healthy worker re-drains them (claimNextForUser only claims
// "queued"). claimNextForUser's correctness DEPENDS on this reaper (design §4).
crons.interval(
  "reap stale processing messages",
  { minutes: 2 },
  internal.messages.reapStaleProcessing,
  {},
);

// Idle reaping DISABLED — every user's agent must stay warm 24/7 (operator
// requirement 2026-06-17). Previously free-tier containers idle > 30 min were
// flipped desired="stopped" for $0 idle compute; now NO tier is reaped, so a
// user's container lives until an explicit stop or a stale-heartbeat relaunch.
// reapIdleInstances{,Impl} are kept (callable manually) for easy re-enable.
// ponytail: trades free-tier idle cost for always-warm. CEILING — every user =
// one always-on container (Chrome+Hermes+worker); a single VM (e2-standard-2)
// holds only a handful, so re-enable this cron (or add bigger/more VMs + a
// scheduler) before onboarding many free users.

// Housekeeping: mark expired-but-still-"active" pairing tokens "expired" (consume
// already self-checks expiry; this keeps the one-active-per-user invariant clean).
crons.interval(
  "expire stale pairing tokens",
  { minutes: 30 },
  internal.pairing.expireStaleTokens,
  {},
);

crons.interval(
  "expire stale crew tasks",
  { minutes: 30 },
  internalAny.crew.expirePending,
  {},
);

export default crons;
