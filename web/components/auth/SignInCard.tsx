"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuthActions } from "@convex-dev/auth/react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmailOtpForm } from "@/components/auth/EmailOtpForm";
import { cn } from "@/lib/utils";

const inputClass = cn(
  "w-full bg-surface-2 border border-border rounded text-ink px-3 h-10",
  "placeholder:text-faint outline-none transition-colors",
  "focus-visible:ring-2 focus-visible:ring-lime focus-visible:border-lime",
);

type PasswordFlow = "signIn" | "signUp";

function messageFromError(err: unknown): string {
  return err instanceof Error && err.message ? err.message : String(err);
}

function Divider({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-3" aria-hidden>
      <span className="h-px flex-1 bg-border" />
      <span className="text-xs text-faint lowercase">{label}</span>
      <span className="h-px flex-1 bg-border" />
    </div>
  );
}

export function SignInCard() {
  const router = useRouter();
  const { signIn } = useAuthActions();

  const [flow, setFlow] = useState<PasswordFlow>("signIn");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [googlePending, setGooglePending] = useState(false);
  const [pwPending, setPwPending] = useState(false);

  async function handleGoogle() {
    if (googlePending) return;
    setError(null);
    setGooglePending(true);
    try {
      await signIn("google");
      // signIn("google") redirects out to the OAuth provider; on return the
      // session is established and the user is routed to /connect.
      router.push("/connect");
    } catch (err) {
      setError(messageFromError(err) || "couldn't start google sign-in.");
      setGooglePending(false);
    }
  }

  async function handlePassword(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (pwPending) return;
    setError(null);
    setPwPending(true);
    try {
      await signIn("password", { email, password, flow });
      router.push("/connect");
    } catch (err) {
      const fallback =
        flow === "signUp"
          ? "couldn't create that account. it may already exist."
          : "wrong email or password.";
      setError(messageFromError(err) || fallback);
    } finally {
      setPwPending(false);
    }
  }

  return (
    <Card className="w-full max-w-sm rise" data-testid="signin-card">
      <div className="flex flex-col gap-5">
        {/* 1) google */}
        <Button
          type="button"
          variant="secondary"
          className="w-full lowercase"
          onClick={handleGoogle}
          disabled={googlePending}
        >
          {googlePending ? "redirecting…" : "continue with google"}
        </Button>

        <Divider label="or with a code" />

        {/* 2) email one-time code */}
        <EmailOtpForm />

        <Divider label="or with a password" />

        {/* 3) email + password (dev/e2e + fallback) */}
        <form onSubmit={handlePassword} className="flex flex-col gap-3">
          <label className="flex flex-col gap-1.5">
            <span className="text-xs text-faint lowercase">email</span>
            <input
              className={inputClass}
              type="email"
              autoComplete="email"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </label>

          <label className="flex flex-col gap-1.5">
            <span className="text-xs text-faint lowercase">password</span>
            <input
              className={inputClass}
              type="password"
              autoComplete={flow === "signUp" ? "new-password" : "current-password"}
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>

          {error ? (
            <p className="text-sm text-danger lowercase" role="alert">
              {error}
            </p>
          ) : null}

          <Button
            type="submit"
            variant="primary"
            className="lowercase"
            disabled={pwPending || email.length === 0 || password.length === 0}
          >
            {pwPending
              ? flow === "signUp"
                ? "creating…"
                : "signing in…"
              : flow === "signUp"
                ? "sign up"
                : "sign in"}
          </Button>

          <button
            type="button"
            className="text-xs text-faint hover:text-muted lowercase transition-colors self-start"
            onClick={() => {
              setFlow((f) => (f === "signIn" ? "signUp" : "signIn"));
              setError(null);
            }}
          >
            {flow === "signIn"
              ? "new here? create an account"
              : "already have an account? sign in"}
          </button>
        </form>
      </div>
    </Card>
  );
}
