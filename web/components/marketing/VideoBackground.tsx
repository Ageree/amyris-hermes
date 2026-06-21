// Fixed, full-bleed looping video background — dhizume on her throne in the
// moonlit hall — sitting behind ALL page content. Desktop (16:9) and mobile
// (9:16) sources are swapped by breakpoint so each viewport gets the right crop.
// A dark scrim over the video keeps foreground text readable (WCAG contrast).
// Each clip is a boomerang (plays forward then reverse) so the loop is seamless.
// Pure HTML — no client JS. Reduced-motion users see the static poster instead
// (the videos are hidden in CSS; the poster image carries the same frame).
export function VideoBackground() {
  return (
    <div aria-hidden className="video-bg">
      {/* desktop 16:9 */}
      <video
        className="video-bg-media hidden sm:block"
        autoPlay
        muted
        loop
        playsInline
        preload="auto"
        poster="/dhizume/bg-desktop.jpg"
      >
        <source src="/dhizume/bg-desktop.mp4" type="video/mp4" />
      </video>
      {/* mobile 9:16 */}
      <video
        className="video-bg-media block sm:hidden"
        autoPlay
        muted
        loop
        playsInline
        preload="auto"
        poster="/dhizume/bg-mobile.jpg"
      >
        <source src="/dhizume/bg-mobile.mp4" type="video/mp4" />
      </video>
      {/* dark scrim — readability over the moving image */}
      <div className="video-bg-scrim" />
    </div>
  );
}
