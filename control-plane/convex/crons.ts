import { cronJobs } from "convex/server";
import { internal } from "./_generated/api";

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

// Flip free-tier containers idle past the TTL to desired="stopped" so the
// controller stops them ($0 idle compute). Paid stays warm.
crons.interval(
  "reap idle fleet instances",
  { minutes: 5 },
  internal.fleet.reapIdleInstances,
  {},
);

// Housekeeping: mark expired-but-still-"active" pairing tokens "expired" (consume
// already self-checks expiry; this keeps the one-active-per-user invariant clean).
crons.interval(
  "expire stale pairing tokens",
  { minutes: 30 },
  internal.pairing.expireStaleTokens,
  {},
);

export default crons;
