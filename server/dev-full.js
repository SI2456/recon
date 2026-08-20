import { spawn } from "node:child_process";

const commands = [
  { name: "api", command: "python", args: ["server/app.py"] },
  { name: "web", command: "npm", args: ["run", "dev"] },
];

const children = commands.map(({ name, command, args }) => {
  const child = spawn(command, args, { shell: true, stdio: ["ignore", "pipe", "pipe"] });

  child.stdout.on("data", (data) => process.stdout.write(`[${name}] ${data}`));
  child.stderr.on("data", (data) => process.stderr.write(`[${name}] ${data}`));
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
