/**
 * Run the project's Python interpreter, whatever platform this is.
 *
 * The npm scripts used to spell the path as `server\venv\Scripts\python.exe`,
 * which only exists on Windows — every backend script was unrunnable on macOS
 * and Linux even though the README documents them there. This resolves the
 * virtualenv's interpreter for the current platform, falls back to whatever
 * `python3`/`python` is on PATH, and forwards arguments and exit code through.
 *
 *   node server/scripts/py.js -m uvicorn app.main:app --app-dir server
 */
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const isWindows = process.platform === "win32";

// Every layout the setup instructions can leave behind: a venv inside server/
// (what the npm scripts assume) or one at the repo root.
const candidates = [
  path.join(repoRoot, "server", "venv", isWindows ? "Scripts" : "bin", isWindows ? "python.exe" : "python"),
  path.join(repoRoot, "venv", isWindows ? "Scripts" : "bin", isWindows ? "python.exe" : "python"),
  path.join(repoRoot, ".venv", isWindows ? "Scripts" : "bin", isWindows ? "python.exe" : "python"),
];

const venvPython = candidates.find(existsSync);
const interpreter = venvPython || (isWindows ? "python" : "python3");

if (!venvPython) {
  console.warn(
    `[py] No virtualenv found under server/venv — falling back to '${interpreter}' on PATH.\n` +
      "[py] To create one: python -m venv server/venv && " +
      (isWindows ? "server\\venv\\Scripts\\pip" : "server/venv/bin/pip") +
      " install -r server/requirements.txt",
  );
}

const child = spawn(interpreter, process.argv.slice(2), {
  cwd: repoRoot,
  stdio: "inherit",
  // shell:false so an argument containing a space is passed through intact.
  shell: false,
});

child.on("error", (error) => {
  console.error(`[py] Could not start '${interpreter}': ${error.message}`);
  process.exit(1);
});
child.on("exit", (code, signal) => {
  process.exit(signal ? 1 : (code ?? 0));
});
