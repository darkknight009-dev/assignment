#!/usr/bin/env node
/**
 * Preflight guard for `npm run dev`.
 *
 * Catches the two failure modes seen in practice before they produce a
 * confusing "internal server error":
 *   1. node_modules partially wiped (key packages missing)
 *   2. stale/corrupt .next build cache
 * Then verifies the Python engine is importable, since the app shells out
 * to it for every generate request.
 */
import { existsSync, rmSync, statSync } from "node:fs";
import { spawnSync } from "node:child_process";
import path from "node:path";

const webDir = process.cwd();
const problems = [];

// 1) node_modules sanity
for (const pkg of ["next", "react", "react-dom"]) {
  if (!existsSync(path.join(webDir, "node_modules", pkg))) {
    problems.push(`node_modules/${pkg} is missing (install got wiped)`);
  }
}

// 2) .next cache — if a previous dev run died mid-write, clear it
const nextDir = path.join(webDir, ".next");
if (existsSync(nextDir)) {
  try {
    if (!statSync(path.join(nextDir, "build-manifest.json")) && !existsSync(path.join(nextDir, "cache"))) {
      problems.push(".next cache looks incomplete");
    }
  } catch {
    problems.push(".next cache looks incomplete");
  }
  if (problems.some((p) => p.includes(".next"))) {
    rmSync(nextDir, { recursive: true, force: true });
    console.log("[preflight] cleared stale .next cache");
  }
}

if (problems.some((p) => p.includes("node_modules"))) {
  console.error("[preflight] dependencies are damaged. Run:\n\n    npm ci\n\nthen start again.");
  process.exit(1);
}

// 3) python engine reachable?
const root = path.resolve(webDir, "..");
const py = spawnSync("python3", ["-c", "import minireport.webapi"], {
  cwd: root,
  env: { ...process.env, PYTHONPATH: path.join(root, "src") },
  encoding: "utf8",
});
if (py.status !== 0) {
  console.error("[preflight] python engine not importable (minireport.webapi).");
  console.error("            Run from the repo root:  pip install -e .");
  console.error("            Detail:", (py.stderr || "").trim().split("\n").slice(-2).join(" | "));
  process.exit(1);
}

console.log("[preflight] deps ok · engine ok — starting dev server");
