import type { Metadata } from "next";
import { SignInCard } from "@/components/auth/SignInCard";

export const metadata: Metadata = {
  title: "sign in — hermes",
};

export default function SignInPage() {
  return (
    <main className="mx-auto flex min-h-dvh max-w-md flex-col items-center justify-center gap-6 px-6">
      <div className="flex flex-col items-center gap-2 text-center">
        <span className="font-mono text-lg text-lime lowercase">hermes</span>
        <h1 className="text-sm text-muted lowercase">sign in to your assistant</h1>
      </div>
      <SignInCard />
    </main>
  );
}
