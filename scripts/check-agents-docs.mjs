import { existsSync, readFileSync } from "node:fs";

const ROOT = new URL("..", import.meta.url);
const docs = ["AGENTS.md", "CLAUDE.md", "README.md"];
const requiredSnippets = {
  "AGENTS.md": ["GitNexus", "gitnexus_impact", "gitnexus_detect_changes"],
  "CLAUDE.md": ["GitNexus", "gitnexus_impact", "gitnexus_detect_changes"],
  "README.md": ["npm run setup", "npm run dev", "npm run check"],
};

const referencedSkillPattern = /`(\.claude\/skills\/[^`]+\/SKILL\.md)`/g;
const violations = [];

for (const doc of docs) {
  const url = new URL(doc, ROOT);
  if (!existsSync(url)) {
    violations.push(`${doc} is missing`);
    continue;
  }
  const content = readFileSync(url, "utf8");
  for (const snippet of requiredSnippets[doc]) {
    if (!content.includes(snippet)) {
      violations.push(`${doc} must mention ${snippet}`);
    }
  }
  for (const match of content.matchAll(referencedSkillPattern)) {
    if (!existsSync(new URL(match[1], ROOT))) {
      violations.push(`${doc} references missing ${match[1]}`);
    }
  }
}

if (violations.length > 0) {
  console.error("Agent documentation freshness checks failed:");
  for (const violation of violations) console.error(`- ${violation}`);
  process.exit(1);
}

console.log("Agent documentation references are current.");
