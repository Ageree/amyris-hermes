/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // The Convex API stub the app imports via the @cp/* alias is vendored INSIDE
  // web/ (./cp-generated), so the build is self-contained — no outside-root file
  // tracing or Vercel "include files outside the Root Directory" toggle needed.
};

export default nextConfig;
