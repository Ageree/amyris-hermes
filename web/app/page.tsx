import { VideoBackground } from "@/components/marketing/VideoBackground";
import { Hero } from "@/components/marketing/Hero";

// Public landing — no auth. The wallpaper is the brand surface: one full-bleed
// image, one iMessage entry point, one login path.
export default function Home() {
  return (
    <div className="relative flex min-h-dvh flex-col">
      <VideoBackground />
      <main id="main" className="flex-1">
        <Hero />
      </main>
    </div>
  );
}
