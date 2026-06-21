"use client";

import { useState } from "react";
import { useAuthActions } from "@convex-dev/auth/react";
import { Button } from "@/components/ui/button";

// the top-bar sign-out control. signs out via convex auth, then lands the user
// back on the public landing. middleware will keep protected routes gated.
export function SignOutButton() {
  const { signOut } = useAuthActions();
  const [pending, setPending] = useState(false);

  async function handleSignOut() {
    setPending(true);
    try {
      await signOut();
      // hard redirect (not router.push): tears the dashboard down immediately so
      // no auth-gated query (e.g. currentUser) fires unauthenticated mid-
      // transition, and lands the user cleanly on the public home page.
      window.location.href = "/";
    } catch {
      // sign-out is best-effort from the UI; re-enable so the user can retry.
      setPending(false);
    }
  }

  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={handleSignOut}
      disabled={pending}
      aria-label="sign out"
    >
      {pending ? "signing out…" : "sign out"}
    </Button>
  );
}
