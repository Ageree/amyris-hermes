import { Nav } from "@/components/marketing/Nav";
import { Hero } from "@/components/marketing/Hero";
import { Capabilities } from "@/components/marketing/Capabilities";
import { HowItWorks } from "@/components/marketing/HowItWorks";
import { Showcase } from "@/components/marketing/Showcase";
import { TierGrid } from "@/components/marketing/TierGrid";
import { Faq } from "@/components/marketing/Faq";
import { CtaBand } from "@/components/marketing/CtaBand";
import { Footer } from "@/components/marketing/Footer";

// Public marketing landing — no auth. All sections are server components; the
// only interactivity is plain navigation + native <details> in the FAQ. Section
// order intentionally varies layout family (split → bento → flow → marquee →
// grid → accordion → band) so no two adjacent sections read the same.
export default function Home() {
  return (
    <div className="relative flex min-h-dvh flex-col">
      <Nav />
      <main id="main" className="flex-1">
        <Hero />
        <Capabilities />
        <HowItWorks />
        <Showcase />
        <TierGrid />
        <Faq />
        <CtaBand />
      </main>
      <Footer />
    </div>
  );
}
