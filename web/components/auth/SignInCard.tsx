"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuthActions } from "@convex-dev/auth/react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

// Email + password only. Google and email-code were removed: their backend
// secrets (AUTH_GOOGLE_ID/SECRET, AUTH_RESEND_KEY) are not set on the
// deployment, so offering those buttons only produced errors for new users.
// Re-add a method here the same day its secrets land in the Convex env.

const inputClass = cn(
  "w-full bg-surface-2 border border-border rounded text-ink px-3 h-10",
  "placeholder:text-faint outline-none transition-colors",
  "focus-visible:ring-2 focus-visible:ring-lime focus-visible:border-lime",
);

type PasswordFlow = "signIn" | "signUp";
const MIN_PASSWORD = 8; // mirrors validatePasswordRequirements in convex/auth.ts

function messageFromError(err: unknown): string {
  return err instanceof Error && err.message ? err.message : String(err);
}

export function SignInCard() {
  const router = useRouter();
  const { signIn } = useAuthActions();

  const [flow, setFlow] = useState<PasswordFlow>("signIn");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pwPending, setPwPending] = useState(false);

  const tooShort = flow === "signUp" && password.length > 0 && password.length < MIN_PASSWORD;

  function switchFlow(next: PasswordFlow) {
    setFlow(next);
    setError(null);
  }

  async function handlePassword(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (pwPending) return;
    setError(null);
    if (flow === "signUp" && password.length < MIN_PASSWORD) {
      setError(`password must be at least ${MIN_PASSWORD} characters.`);
      return;
    }
    setPwPending(true);
    try {
      await signIn("password", { email, password, flow });
      // new users go to the pairing wizard to connect a channel first; returning
      // users land straight on their dashboard.
      router.push(flow === "signUp" ? "/connect" : "/dashboard");
    } catch (err) {
      const fallback =
        flow === "signUp"
          ? "couldn't create that account — it may already exist. try signing in."
          : "wrong email or password — or no account yet. try sign up.";
      setError(messageFromError(err) || fallback);
    } finally {
      setPwPending(false);
    }
  }

  return (
    <Card className="w-full max-w-sm rise" data-testid="signin-card">
      <div className="flex flex-col gap-5">
        {/* explicit sign in / sign up choice — no hidden toggle, so new users
            don't fall into "sign in" when they meant to create an account */}
        <div
          role="tablist"
          aria-label="sign in or create an account"
          className="grid grid-cols-2 gap-1 rounded bg-surface-2 p-1"
        >
          {(["signIn", "signUp"] as const).map((f) => (
            <button
              key={f}
              role="tab"
              type="button"
              aria-selected={flow === f}
              data-testid={f === "signUp" ? "tab-signup" : "tab-signin"}
              onClick={() => switchFlow(f)}
              className={cn(
                "h-9 rounded text-sm lowercase transition-colors",
                flow === f
                  ? "bg-surface text-ink shadow-sm"
                  : "text-faint hover:text-muted",
              )}
            >
              {f === "signIn" ? "sign in" : "sign up"}
            </button>
          ))}
        </div>

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
              minLength={flow === "signUp" ? MIN_PASSWORD : undefined}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
            {flow === "signUp" ? (
              <span
                className={cn(
                  "text-xs lowercase",
                  tooShort ? "text-danger" : "text-faint",
                )}
              >
                at least {MIN_PASSWORD} characters
              </span>
            ) : null}
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
                ? "create account"
                : "sign in"}
          </Button>
        </form>
      </div>
    </Card>
  );
}
