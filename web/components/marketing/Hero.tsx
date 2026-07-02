import Link from "next/link";
import { IMESSAGE_NUMBER } from "@/lib/deeplinks";
import { HoverButton } from "@/components/ui/hover-button";

const START_MESSAGE = "start";

const startHref = IMESSAGE_NUMBER
  ? `imessage://${encodeURIComponent(IMESSAGE_NUMBER)}?body=${encodeURIComponent(START_MESSAGE)}`
  : "imessage://";

// The fold: the ASCII meadow wallpaper is the product signal. Copy stays low
// and left so the cloud/sky remain visible; the login affordance lives in the
// hero's top-right corner as requested.
export function Hero() {
  return (
    <section className="relative flex min-h-dvh overflow-hidden px-5 py-5 sm:px-8 sm:py-7 lg:px-12">
      <header className="absolute right-5 top-5 z-10 sm:right-8 sm:top-7 lg:right-12">
        <Link
          href="/signin"
          className="inline-flex h-11 items-center justify-center rounded-[var(--radius)] border border-white/35 bg-canvas/35 px-5 text-sm font-semibold text-ink shadow-[0_1px_0_rgba(255,255,255,0.22)_inset,0_12px_32px_-18px_rgba(3,22,10,0.75)] backdrop-blur-md transition-[background-color,border-color,transform] duration-200 hover:-translate-y-px hover:border-white/55 hover:bg-canvas/50 active:translate-y-0"
        >
          Войти
        </Link>
      </header>

      <div className="rise relative z-10 mt-auto w-full max-w-4xl pb-5 sm:pb-9 lg:pb-12">
        <h1 className="font-display mt-4 max-w-[11ch] text-balance text-6xl font-semibold leading-[0.92] text-ink [text-shadow:0_2px_28px_rgba(0,0,0,0.68)] sm:text-8xl lg:text-9xl">
          dhizume
        </h1>

        <p className="mt-6 max-w-xl text-pretty text-base font-medium leading-relaxed text-ink/90 [text-shadow:0_1px_18px_rgba(0,0,0,0.72)] sm:text-lg">
          ИИ который действительно полезен
        </p>

        <div className="mt-8 flex flex-col gap-3 sm:flex-row">
          <HoverButton
            href={startHref}
            data-testid="start-imessage"
          >
            Начать
          </HoverButton>
        </div>
      </div>
    </section>
  );
}
