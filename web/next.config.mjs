/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // The generated Convex API (imported via the @cp/* alias) lives outside web/;
  // allow Next to resolve + transpile it from the sibling control-plane dir.
  outputFileTracingRoot: new URL("..", import.meta.url).pathname,
};

export default nextConfig;
