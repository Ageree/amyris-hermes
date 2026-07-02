import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["**/*.test.ts"],
    retry: 1,
    coverage: {
      provider: "v8",
      reporter: ["text", "json-summary"],
      thresholds: {
        branches: 60,
        functions: 70,
        lines: 70,
        statements: 70,
      },
    },
  },
  resolve: {
    alias: {
      "@/": new URL("./", import.meta.url).pathname,
      "@cp/api": new URL("./cp-generated/api", import.meta.url).pathname,
    },
  },
});
