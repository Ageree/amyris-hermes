import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["**/*.test.ts"],
  },
  resolve: {
    alias: {
      "@/": new URL("./", import.meta.url).pathname,
      "@cp/api": new URL("./cp-generated/api", import.meta.url).pathname,
    },
  },
});
