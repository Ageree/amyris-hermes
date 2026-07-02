import { execFileSync } from "node:child_process";
import { statSync } from "node:fs";
import { extname } from "node:path";

const ROOT = new URL("..", import.meta.url);
const DEFAULT_LIMIT = 512 * 1024;
const LOCKFILE_LIMIT = 2 * 1024 * 1024;
const MEDIA_LIMIT = 5 * 1024 * 1024;

const mediaExtensions = new Set([
  ".gif",
  ".jpg",
  ".jpeg",
  ".mp3",
  ".mp4",
  ".mov",
  ".pdf",
  ".png",
  ".webp",
]);

function trackedFiles() {
  const output = execFileSync("git", ["ls-files", "-z"], {
    cwd: ROOT,
    encoding: "utf8",
  });
  return output.split("\0").filter(Boolean);
}

function limitFor(file) {
  if (file.endsWith("package-lock.json")) return LOCKFILE_LIMIT;
  if (mediaExtensions.has(extname(file).toLowerCase())) return MEDIA_LIMIT;
  return DEFAULT_LIMIT;
}

const violations = [];

for (const file of trackedFiles()) {
  const size = statSync(new URL(file, ROOT)).size;
  const limit = limitFor(file);
  if (size > limit) {
    violations.push({ file, size, limit });
  }
}

if (violations.length > 0) {
  console.error("Large tracked files exceed the repository budget:");
  for (const { file, size, limit } of violations) {
    console.error(
      `- ${file}: ${(size / 1024).toFixed(1)} KiB > ${(limit / 1024).toFixed(1)} KiB`,
    );
  }
  process.exit(1);
}

console.log("Large-file budget passed.");
