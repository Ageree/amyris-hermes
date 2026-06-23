import type { Metadata } from "next";
import { ConvexAuthNextjsServerProvider } from "@convex-dev/auth/nextjs/server";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { Cormorant_Garamond } from "next/font/google";
import { ConvexClientProvider } from "@/components/ConvexClientProvider";
import { RevealObserver } from "@/components/RevealObserver";
import "./globals.css";

// Geist (body/ui/mono) is self-hosted via the `geist` package — no network at
// runtime. Cormorant Garamond (display) is self-hosted by next/font at BUILD
// time (latin subset inlined into the build), so the Vercel build stays
// deterministic with no runtime font fetch. A high-contrast romantic garalde
// serif is the native typography of dhizume's victorian-gothic world; used for
// display headlines only, Geist carries all body + ui. The CSS variables feed
// the --font-sans / --font-mono / --font-display tokens in globals.css (@theme).
const display = Cormorant_Garamond({
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  style: ["normal", "italic"],
  variable: "--font-cormorant",
  display: "swap",
});
export const metadata: Metadata = {
  metadataBase: new URL("https://hermes-fleet-web.vercel.app"),
  title: "dhizume, an assistant that lives in imessage & telegram",
  description:
    "meet dhizume: a real assistant with a real browser. she books, buys, digs through the web, and reports back, right in the chat you already use. lowercase by design.",
  icons: { icon: "/dhizume/avatar.png" },
  openGraph: {
    title: "dhizume, an assistant that lives in your chat",
    description:
      "a real assistant with a real browser. she books, buys, researches, and reports back in imessage or telegram.",
    type: "website",
    images: ["/dhizume/og.png"],
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <ConvexAuthNextjsServerProvider>
      <html
        lang="en"
        suppressHydrationWarning
        className={`${GeistSans.variable} ${GeistMono.variable} ${display.variable}`}
      >
        <body className="min-h-dvh bg-canvas text-ink antialiased">
          {/* no-js fallback: never leave reveal content hidden without JS */}
          <noscript>
            <style>{`.reveal{opacity:1 !important;transform:none !important}`}</style>
          </noscript>
          {/* Skip link — first focusable element; jumps keyboard users past nav. */}
          <a href="#main" className="sr-only skip-link">
            skip to main content
          </a>
          {/* Fine grain over the whole page — fixed + pointer-events-none, cheap. */}
          <div aria-hidden className="grain" />
          {/* Reveals .reveal elements once as they scroll into view. */}
          <RevealObserver />
          <ConvexClientProvider>{children}</ConvexClientProvider>
        </body>
      </html>
    </ConvexAuthNextjsServerProvider>
  );
}
