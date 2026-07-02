// Fixed, full-bleed animated wallpaper. The MP4 keeps the source quality sharper
// and lighter than the GIF, while the poster covers initial load and reduced motion.
export function VideoBackground() {
  return (
    <div aria-hidden className="wallpaper-bg">
      <video
        autoPlay
        loop
        muted
        playsInline
        preload="auto"
        poster="/ascii-magic/wallpaper.png"
        className="wallpaper-bg-media"
      >
        <source src="/ascii-magic/wallpaper.mp4" type="video/mp4" />
      </video>
      <div className="wallpaper-bg-vignette" />
    </div>
  );
}
