import { ConnectWizard } from "@/components/connect/ConnectWizard";

// /connect — the pairing wizard. Auth-gated by middleware (unauthed → /signin),
// so this server component can render the client wizard directly; every Convex
// call inside carries the verified JWT.
export default function ConnectPage() {
  return (
    <main id="main" className="mx-auto flex min-h-dvh w-full max-w-2xl flex-col justify-center px-6 py-16">
      <ConnectWizard />
    </main>
  );
}
