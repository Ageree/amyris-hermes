"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuthActions } from "@convex-dev/auth/react";
import { Button } from "@/components/ui/button";

// the top-bar sign-out control. signs out via convex auth, then lands the user
// back on the public landing. middleware will keep protected routes gated.
export function SignOutButton() {
  const router = useRouter();
  const { signOut } = useAuthActions();
  const [pending, setPending] = useState(false);

  async function handleSignOut() {
    setPending(true);
    try {
      await signOut();
      router.push("/");
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
