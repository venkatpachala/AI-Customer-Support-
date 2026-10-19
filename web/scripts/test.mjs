import { readdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { spawnSync } from "node:child_process";

function discover(root) {
  return readdirSync(root, { withFileTypes: true }).flatMap((entry) => {
    const path = join(root, entry.name);
    return entry.isDirectory() ? discover(path) : entry.name.endsWith(".test.mjs") ? [path] : [];
  });
}
const files = discover(resolve("scripts"));
if (!files.length) throw new Error("No script tests were discovered");
for (const args of [
  ["--test", ...files],
  ["--experimental-strip-types", "--test", "src/lib/app-data/app-data.test.ts", "src/lib/app-data/readiness-schedule.test.ts",
   "src/lib/auth/gate-identity.test.ts", "src/lib/auth/sign-in-gate.test.ts", "src/lib/preview-path-prefix.test.ts"],
]) {
  const result = spawnSync(process.execPath, args, { stdio: "inherit", shell: false });
  if (result.status !== 0) process.exit(result.status || 1);
}
