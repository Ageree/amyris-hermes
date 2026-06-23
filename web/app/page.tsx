import { VideoBackground } from "@/components/marketing/VideoBackground";
import { Nav } from "@/components/marketing/Nav";
import { Hero } from "@/components/marketing/Hero";
import { Film } from "@/components/marketing/Film";
import { RealThings } from "@/components/marketing/RealThings";
import { Channels } from "@/components/marketing/Channels";
import { TierGrid } from "@/components/marketing/TierGrid";
import { Faq } from "@/components/marketing/Faq";
import { CtaBand } from "@/components/marketing/CtaBand";
import { Footer } from "@/components/marketing/Footer";

// Public marketing landing — no auth. Narrative arc:
//   hero (dhizume throne wallpaper + the promise)
//   → film: watch her actually work in imessage (the proof, #how)
//   → real things she finishes (capabilities bento)
//   → lives where you already text (channels)
//   → pricing → faq → closing cta.
export default function Home() {
  return (
    <div className="relative flex min-h-dvh flex-col">
      {/* Looping dhizume-on-her-throne video — landing only. fixed + z-index:-2,
          so authed surfaces (dashboard/connect/signin) keep the plain canvas bg. */}
      <VideoBackground />
      <Nav />
      <main id="main" className="flex-1">
        <Hero />
        <Film />
        <RealThings />
        <Channels />
        <TierGrid />
        <Faq />
        <CtaBand />
      </main>
      <Footer />
    </div>
  );
}
