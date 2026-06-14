import type { Metadata } from "next";
import { ConvexAuthNextjsServerProvider } from "@convex-dev/auth/nextjs/server";
import { ConvexClientProvider } from "@/components/ConvexClientProvider";
import "./globals.css";

export const metadata: Metadata = {
  title: "hermes — your assistant, on imessage & telegram",
  description:
    "a real assistant with a real browser. sign up, tap a button, and it lands in your imessage or telegram. lowercase by design.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <ConvexAuthNextjsServerProvider>
      <html lang="en" suppressHydrationWarning>
        <body className="min-h-dvh bg-canvas text-ink antialiased">
          {/* Skip link — first focusable element; jumps keyboard users past nav (item 6). */}
          <a href="#main" className="sr-only skip-link">
            skip to main content
          </a>
          <ConvexClientProvider>{children}</ConvexClientProvider>
        </body>
      </html>
    </ConvexAuthNextjsServerProvider>
  );
}
