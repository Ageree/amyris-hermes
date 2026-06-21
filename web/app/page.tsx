import { Nav } from "@/components/marketing/Nav";
import { Hero } from "@/components/marketing/Hero";
import { PhoneShowcase } from "@/components/marketing/PhoneShowcase";
import { TierGrid } from "@/components/marketing/TierGrid";
import { Faq } from "@/components/marketing/Faq";
import { CtaBand } from "@/components/marketing/CtaBand";
import { Footer } from "@/components/marketing/Footer";

// Public marketing landing — no auth. The fold is the clean dhizume throne-room
// wallpaper (nothing covers it). On scroll: the living telegram thread
// (PhoneShowcase) where dhizume takes real tasks and texts back real artifacts,
// then pricing → faq → cta.
export default function Home() {
  return (
    <div className="relative flex min-h-dvh flex-col">
      <Nav />
      <main id="main" className="flex-1">
        <Hero />
        <PhoneShowcase />
        <TierGrid />
        <Faq />
        <CtaBand />
      </main>
      <Footer />
    </div>
  );
}
