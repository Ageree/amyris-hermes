import { Nav } from "@/components/marketing/Nav";
import { Hero } from "@/components/marketing/Hero";
import { TierGrid } from "@/components/marketing/TierGrid";
import { Footer } from "@/components/marketing/Footer";

// Public marketing landing — no auth. All sections are server components; the
// only interactivity is plain <Link> navigation to /signin.
export default function Home() {
  return (
    <div className="flex min-h-dvh flex-col">
      <Nav />
      <main className="flex-1">
        <Hero />
        <TierGrid />
      </main>
      <Footer />
    </div>
  );
}
