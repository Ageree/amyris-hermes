"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuthActions } from "@convex-dev/auth/react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const inputClass = cn(
  "w-full bg-surface-2 border border-border rounded text-ink px-3 h-10",
  "placeholder:text-faint outline-none transition-colors",
  "focus-visible:ring-2 focus-visible:ring-lime focus-visible:border-lime",
);

type Step = "email" | "code";

function messageFromError(err: unknown): string {
  return err instanceof Error && err.message ? err.message : String(err);
}

export function EmailOtpForm() {
  const router = useRouter();
  const { signIn } = useAuthActions();

  const [step, setStep] = useState<Step>("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function handleSendCode(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (pending) return;
    setError(null);
    setPending(true);
    try {
      await signIn("resend-otp", { email });
      setStep("code");
    } catch {
      // step 1 commonly fails when AUTH_RESEND_KEY is unset on the backend.
      setError("couldn't send a code right now. try google or password instead.");
    } finally {
      setPending(false);
    }
  }

  async function handleVerifyCode(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (pending) return;
    setError(null);
    setPending(true);
    try {
      await signIn("resend-otp", { email, code });
      router.push("/connect");
    } catch (err) {
      setError(messageFromError(err) || "that code didn't work. try again.");
    } finally {
      setPending(false);
    }
  }

  if (step === "code") {
    return (
      <form onSubmit={handleVerifyCode} className="flex flex-col gap-3">
        <p className="text-sm text-muted lowercase">
          we sent a code to{" "}
          <span className="text-ink">{email}</span>. enter it below.
        </p>
        <label className="flex flex-col gap-1.5">
          <span className="text-xs text-faint lowercase">code</span>
          <input
            className={cn(inputClass, "font-mono tracking-[0.3em]")}
            type="text"
            inputMode="numeric"
            autoComplete="one-time-code"
            placeholder="123456"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            required
            autoFocus
          />
        </label>

        {error ? (
          <p className="text-sm text-danger lowercase" role="alert">
            {error}
          </p>
        ) : null}

        <Button type="submit" variant="primary" disabled={pending || code.length === 0}>
          {pending ? "verifying…" : "verify code"}
        </Button>

        <button
          type="button"
          className="text-xs text-faint hover:text-muted lowercase transition-colors"
          onClick={() => {
            setStep("email");
            setCode("");
            setError(null);
          }}
        >
          use a different email
        </button>
      </form>
    );
  }

  return (
    <form onSubmit={handleSendCode} className="flex flex-col gap-3">
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

      {error ? (
        <p className="text-sm text-danger lowercase" role="alert">
          {error}
        </p>
      ) : null}

      <Button type="submit" variant="primary" disabled={pending || email.length === 0}>
        {pending ? "sending…" : "email me a code"}
      </Button>
    </form>
  );
}
