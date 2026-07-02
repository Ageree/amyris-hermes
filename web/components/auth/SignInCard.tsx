"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuthActions } from "@convex-dev/auth/react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const inputClass = cn(
  "w-full bg-surface-2 border border-border rounded text-ink px-3 h-10",
  "placeholder:text-faint outline-none transition-colors",
  "focus-visible:ring-2 focus-visible:ring-lime focus-visible:border-lime",
);

type PasswordFlow = "signIn" | "signUp";
type AuthMode = "phone" | "email";
type PhoneStep = "phone" | "code";

const MIN_PASSWORD = 8; // mirrors validatePasswordRequirements in convex/auth.ts

function normalizePhoneInput(raw: string): string {
  const trimmed = raw.trim();
  const digits = trimmed.replace(/\D/g, "");
  if (!digits) return "";
  if (trimmed.startsWith("+")) return `+${digits}`;
  if (/^8\d{10}$/.test(digits)) return `+7${digits.slice(1)}`;
  return `+${digits}`;
}

function isE164(phone: string): boolean {
  return /^\+[1-9]\d{7,14}$/.test(phone);
}

export function SignInCard() {
  const router = useRouter();
  const { signIn } = useAuthActions();

  const [mode, setMode] = useState<AuthMode>("phone");
  const [phoneStep, setPhoneStep] = useState<PhoneStep>("phone");
  const [phone, setPhone] = useState("");
  const [verifiedPhone, setVerifiedPhone] = useState("");
  const [code, setCode] = useState("");
  const [phonePending, setPhonePending] = useState(false);
  const [phoneError, setPhoneError] = useState<string | null>(null);

  const [flow, setFlow] = useState<PasswordFlow>("signIn");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pwPending, setPwPending] = useState(false);
  const [googlePending, setGooglePending] = useState(false);

  const normalizedPhone = normalizePhoneInput(phone);
  const phoneReady = isE164(normalizedPhone);
  const tooShort = flow === "signUp" && password.length > 0 && password.length < MIN_PASSWORD;

  function switchFlow(next: PasswordFlow) {
    setFlow(next);
    setError(null);
  }

  function switchMode(next: AuthMode) {
    setMode(next);
    setError(null);
    setPhoneError(null);
  }

  async function handlePhoneStart(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (phonePending) return;
    setPhoneError(null);
    if (!phoneReady) {
      setPhoneError("Введите номер в международном формате: +79991234567.");
      return;
    }
    setPhonePending(true);
    try {
      await signIn("phone", { phone: normalizedPhone });
      setVerifiedPhone(normalizedPhone);
      setPhoneStep("code");
    } catch {
      setPhoneError("Не удалось отправить код. Проверьте номер и попробуйте еще раз.");
    } finally {
      setPhonePending(false);
    }
  }

  async function handlePhoneCode(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (phonePending) return;
    const enteredCode = code.trim();
    const targetPhone = verifiedPhone || normalizedPhone;
    setPhoneError(null);
    if (!isE164(targetPhone)) {
      setPhoneStep("phone");
      setPhoneError("Сначала введите номер телефона.");
      return;
    }
    if (enteredCode.length < 4) {
      setPhoneError("Введите код из сообщения.");
      return;
    }
    setPhonePending(true);
    try {
      await signIn("phone", { phone: targetPhone, code: enteredCode });
      router.push("/dashboard");
    } catch {
      setPhoneError("Код не подошел или истек. Запросите новый код.");
    } finally {
      setPhonePending(false);
    }
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
      router.push(flow === "signUp" ? "/connect" : "/dashboard");
    } catch {
      setError(
        flow === "signUp"
          ? "couldn't create that account — it may already exist. try signing in."
          : "wrong email or password — or no account yet. try sign up.",
      );
    } finally {
      setPwPending(false);
    }
  }

  async function handleGoogle() {
    if (googlePending) return;
    setError(null);
    setGooglePending(true);
    try {
      await signIn("google", { redirectTo: "/dashboard" });
    } catch {
      setError("couldn't start google sign-in. try again, or use email.");
      setGooglePending(false);
    }
  }

  return (
    <Card className="w-full max-w-sm rise border-white/15 bg-surface/90 backdrop-blur-xl" data-testid="signin-card">
      {mode === "phone" ? (
        <div className="flex flex-col gap-5">
          <div className="flex flex-col gap-1">
            <h2 className="text-lg font-semibold text-ink">Введите номер</h2>
            <p className="text-sm leading-relaxed text-muted">
              Мы отправим код в iMessage/SMS и откроем ваш dashboard.
            </p>
          </div>

          {phoneStep === "phone" ? (
            <form onSubmit={handlePhoneStart} className="flex flex-col gap-3">
              <label className="flex flex-col gap-1.5">
                <span className="text-xs text-faint">Номер телефона</span>
                <input
                  className={inputClass}
                  type="tel"
                  inputMode="tel"
                  autoComplete="tel"
                  placeholder="+79991234567"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  required
                  data-testid="phone-input"
                />
              </label>

              {phoneError ? (
                <p className="text-sm text-danger" role="alert">
                  {phoneError}
                </p>
              ) : null}

              <Button
                type="submit"
                variant="primary"
                disabled={phonePending || !phoneReady}
                data-testid="phone-submit"
              >
                {phonePending ? "Отправляем код..." : "Получить код"}
              </Button>
            </form>
          ) : (
            <form onSubmit={handlePhoneCode} className="flex flex-col gap-3">
              <div className="rounded-[var(--radius)] border border-border bg-surface-2 px-3 py-2 text-sm text-muted">
                Код отправлен на <span className="font-mono text-ink">{verifiedPhone}</span>
              </div>

              <label className="flex flex-col gap-1.5">
                <span className="text-xs text-faint">Код</span>
                <input
                  className={cn(inputClass, "font-mono tracking-[0.22em]")}
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  placeholder="123456"
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  required
                  data-testid="phone-code"
                />
              </label>

              {phoneError ? (
                <p className="text-sm text-danger" role="alert">
                  {phoneError}
                </p>
              ) : null}

              <Button
                type="submit"
                variant="primary"
                disabled={phonePending || code.trim().length < 4}
                data-testid="phone-code-submit"
              >
                {phonePending ? "Проверяем..." : "Войти в dashboard"}
              </Button>

              <button
                type="button"
                className="self-center text-sm text-muted underline-offset-4 transition-colors hover:text-ink hover:underline"
                onClick={() => {
                  setPhoneStep("phone");
                  setCode("");
                  setPhoneError(null);
                }}
              >
                Изменить номер
              </button>
            </form>
          )}

          <button
            type="button"
            className="text-sm text-faint underline-offset-4 transition-colors hover:text-muted hover:underline"
            onClick={() => switchMode("email")}
            data-testid="email-fallback"
          >
            Войти по email
          </button>
        </div>
      ) : (
        <div className="flex flex-col gap-5">
          <button
            type="button"
            className="self-start text-sm text-muted underline-offset-4 transition-colors hover:text-ink hover:underline"
            onClick={() => switchMode("phone")}
          >
            ← вернуться к телефону
          </button>

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
                  "h-9 rounded text-sm transition-colors",
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
                  ? "creating..."
                  : "signing in..."
                : flow === "signUp"
                  ? "create account"
                  : "sign in"}
            </Button>
          </form>

          <div className="flex items-center gap-3" aria-hidden>
            <span className="h-px flex-1 bg-border" />
            <span className="text-xs text-faint lowercase">or</span>
            <span className="h-px flex-1 bg-border" />
          </div>

          <Button
            type="button"
            variant="secondary"
            className="lowercase"
            onClick={handleGoogle}
            disabled={googlePending || pwPending}
            data-testid="google-signin"
          >
            <GoogleIcon />
            {googlePending ? "redirecting..." : "continue with google"}
          </Button>
        </div>
      )}
    </Card>
  );
}

// Google "G" mark — inline SVG, no dependency.
function GoogleIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 18 18" aria-hidden focusable="false">
      <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62Z" />
      <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.8.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.33A9 9 0 0 0 9 18Z" />
      <path fill="#FBBC05" d="M3.97 10.72a5.4 5.4 0 0 1 0-3.44V4.95H.96a9 9 0 0 0 0 8.1l3.01-2.33Z" />
      <path fill="#EA4335" d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58A9 9 0 0 0 .96 4.95l3.01 2.33C4.68 5.16 6.66 3.58 9 3.58Z" />
    </svg>
  );
}
