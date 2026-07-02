import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";

const ROOT = new URL("..", import.meta.url);
const includedPrefixes = [
  "agent/",
  "control-plane/",
  "fleet/",
  "lab/",
  "scripts/",
  "web/",
];
const includedExtensions = new Set([
  ".js",
  ".jsx",
  ".md",
  ".mjs",
  ".py",
  ".ts",
  ".tsx",
]);
const trackedMarker = /\b(?:TODO|FIXME)\([A-Za-z0-9_.#-]+\):/;
const marker = /\b(?:TODO|FIXME)\b/;

function trackedFiles() {
  const output = execFileSync("git", ["ls-files", "-z"], {
    cwd: ROOT,
    encoding: "utf8",
  });
  return output.split("\0").filter(Boolean);
}

function extension(file) {
  const match = file.match(/\.[^.]+$/);
  return match ? match[0] : "";
}

function shouldScan(file) {
  return (
    includedPrefixes.some((prefix) => file.startsWith(prefix)) &&
    includedExtensions.has(extension(file)) &&
    !file.includes("/node_modules/") &&
    !file.includes("/.next/") &&
    !file.includes("/.output/") &&
    !file.includes("/cp-generated/")
  );
}

const violations = [];

for (const file of trackedFiles().filter(shouldScan)) {
  const lines = readFileSync(new URL(file, ROOT), "utf8").split(/\r?\n/);
  lines.forEach((line, index) => {
    if (marker.test(line) && !trackedMarker.test(line)) {
      violations.push(`${file}:${index + 1}: ${line.trim()}`);
    }
  });
}

if (violations.length > 0) {
  console.error("TODO/FIXME markers must include an owner or issue tag:");
  for (const violation of violations) console.error(`- ${violation}`);
  process.exit(1);
}

console.log("Tracked TODO/FIXME markers are tagged.");
