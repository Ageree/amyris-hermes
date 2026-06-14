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

export default crons;
