import type { Metadata } from "next";
import { SignInCard } from "@/components/auth/SignInCard";

export const metadata: Metadata = {
  title: "sign in — hermes",
};

export default function SignInPage() {
  return (
    <main id="main" className="mx-auto flex min-h-dvh max-w-md flex-col items-center justify-center gap-6 px-6">
      <div className="flex flex-col items-center gap-2 text-center">
        {/* wordmark — decorative, not the page heading (item 4) */}
        <span className="font-mono text-lg text-lime lowercase" aria-hidden="true">hermes</span>
        {/* h1 describes the page purpose; the wordmark above is visual decoration (item 4) */}
        <h1 className="text-sm text-muted lowercase">sign in</h1>
      </div>
      <SignInCard />
    </main>
  );
}
