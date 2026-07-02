import { readFileSync } from "node:fs";

const ROOT = new URL("..", import.meta.url);
const manifests = [
  "package.json",
  "web/package.json",
  "control-plane/package.json",
  "agent/package.json",
  "lab/photon-sidecar/package.json",
];

const packageGroups = [
  {
    name: "Convex auth stack",
    packages: ["@auth/core", "@convex-dev/auth", "convex"],
  },
  {
    name: "React runtime",
    packages: ["react", "react-dom"],
  },
  {
    name: "Vitest",
    packages: ["vitest", "@vitest/coverage-v8"],
  },
];

function manifest(path) {
  return JSON.parse(readFileSync(new URL(path, ROOT), "utf8"));
}

function dependencyEntries(pkg) {
  return {
    ...pkg.dependencies,
    ...pkg.devDependencies,
    ...pkg.optionalDependencies,
    ...pkg.peerDependencies,
  };
}

const specsByPackage = new Map();

for (const path of manifests) {
  const pkg = manifest(path);
  for (const [name, spec] of Object.entries(dependencyEntries(pkg))) {
    if (!specsByPackage.has(name)) specsByPackage.set(name, new Map());
    specsByPackage.get(name).set(path, spec);
  }
}

const violations = [];

for (const group of packageGroups) {
  for (const name of group.packages) {
    const specs = specsByPackage.get(name);
    if (!specs || specs.size < 2) continue;
    const uniqueSpecs = new Set(specs.values());
    if (uniqueSpecs.size > 1) {
      violations.push({
        group: group.name,
        name,
        specs: [...specs.entries()],
      });
    }
  }
}

if (violations.length > 0) {
  console.error("Dependency version drift detected:");
  for (const violation of violations) {
    console.error(`- ${violation.group}: ${violation.name}`);
    for (const [path, spec] of violation.specs) {
      console.error(`  ${path}: ${spec}`);
    }
  }
  process.exit(1);
}

console.log("Dependency drift policy passed.");
