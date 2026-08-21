import { spawn } from "node:child_process";

// The API half runs the FastAPI app under server/app/. It used to launch
// server/app.py — the retired stdlib prototype — so `npm run dev:full` and
// `npm run backend` started two different backends with different databases,
// and the frontend's newer endpoints 404'd under the former.
const commands = [
  {
    name: "api",
    command: process.execPath,
    args: [
      "server/scripts/py.js",
      "-m",
      "uvicorn",
      "app.main:app",
      "--app-dir",
      "server",
      "--host",
      "0.0.0.0",
      "--port",
      "4000",
      "--reload",
    ],
  },
  { name: "web", command: "npm", args: ["run", "dev"] },
];

const children = commands.map(({ name, command, args }) => {
  // shell:true only where it is needed (npm resolves to npm.cmd on Windows);
  // the Node launcher is executed directly so its arguments pass through as-is.
  const child = spawn(command, args, { shell: name === "web", stdio: ["ignore", "pipe", "pipe"] });

  child.stdout.on("data", (data) => process.stdout.write(`[${name}] ${data}`));
  child.stderr.on("data", (data) => process.stderr.write(`[${name}] ${data}`));
  child.on("error", (error) => {
    process.stderr.write(`[${name}] failed to start: ${error.message}\n`);
    process.exitCode = 1;
  });
  child.on("exit", (code) => {
    if (code && code !== 0) process.exitCode = code;
  });

  return child;
});

function shutdown() {
  for (const child of children) child.kill();
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
