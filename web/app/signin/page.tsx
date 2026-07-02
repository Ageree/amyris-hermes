import type { Metadata } from "next";
import { SignInCard } from "@/components/auth/SignInCard";

export const metadata: Metadata = {
  title: "Войти · Amyris",
};

export default function SignInPage() {
  return (
    <main
      id="main"
      className="relative mx-auto flex min-h-dvh max-w-md flex-col items-center justify-center gap-6 overflow-hidden px-6"
    >
      <div aria-hidden className="grid-lines absolute inset-0 -z-10" />
      <div aria-hidden className="aurora absolute -top-24 left-1/2 -z-10 h-[360px] w-[520px] -translate-x-1/2" />

      <div className="flex flex-col items-center gap-3 text-center">
        <span
          className="inline-flex items-center gap-2 font-mono text-lg text-lime"
          aria-hidden="true"
        >
          <span className="relative inline-flex h-2.5 w-2.5 items-center justify-center">
            <span className="absolute h-2.5 w-2.5 rounded-full bg-lime/60 ping-ring" />
            <span className="relative h-2 w-2 rounded-full bg-lime pulse-dot" />
          </span>
          Amyris
        </span>
        <h1 className="text-sm text-muted">Вход по номеру телефона</h1>
      </div>
      <SignInCard />
    </main>
  );
}
