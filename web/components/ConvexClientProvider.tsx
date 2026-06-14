"use client";

import { ReactNode } from "react";
import { ConvexReactClient } from "convex/react";
import { ConvexAuthNextjsProvider } from "@convex-dev/auth/nextjs";

// Single browser Convex client, wired to the dev/prod deployment via the public
// URL. ConvexAuthNextjsProvider bridges the Next.js auth cookies <-> Convex so
// useQuery/useMutation calls carry the JWT (every app/* function is gated on it).
const convex = new ConvexReactClient(process.env.NEXT_PUBLIC_CONVEX_URL!);

export function ConvexClientProvider({ children }: { children: ReactNode }) {
  return (
    <ConvexAuthNextjsProvider client={convex}>
      {children}
    </ConvexAuthNextjsProvider>
  );
}
