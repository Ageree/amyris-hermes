import { ConnectWizard } from "@/components/connect/ConnectWizard";

// /connect — the pairing wizard. Auth-gated by middleware (unauthed → /signin),
// so this server component can render the client wizard directly; every Convex
// call inside carries the verified JWT.
//
// ?step=channel skips the plan-picker for already-onboarded users coming from the
// dashboard; any other value (incl. none) starts the full signup flow at "tier".
export default async function ConnectPage({
  searchParams,
}: {
  searchParams: Promise<{ step?: string }>;
}) {
  const { step } = await searchParams;
  const initialStep = step === "channel" ? "channel" : "tier";
  return (
    <main id="main" className="mx-auto flex min-h-dvh w-full max-w-2xl flex-col justify-center px-6 py-16">
      <ConnectWizard initialStep={initialStep} />
    </main>
  );
}
