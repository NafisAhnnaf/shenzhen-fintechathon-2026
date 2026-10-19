// The login service: Better Auth's handler on /api/auth/*. The API forwards those paths here, so the browser sees
// one origin. `node server.mjs --migrate` creates or updates Better Auth's tables and exits.
import { createServer } from "node:http";
import { getMigrations } from "better-auth/db/migration";
import { toNodeHandler } from "better-auth/node";
import { auth } from "./auth.mjs";

if (process.argv.includes("--migrate")) {
  const { runMigrations, toBeCreated, toBeAdded } = await getMigrations(auth.options);
  await runMigrations();
  console.log(`tables created: ${toBeCreated.map((t) => t.table).join(", ") || "none"}; columns added: ${toBeAdded.length}`);
  process.exit(0);
}

const port = Number(process.env.AUTH_PORT || 3001);
const handler = toNodeHandler(auth);
createServer((req, res) => {
  if (req.url === "/health") {
    res.writeHead(200, { "content-type": "application/json" }).end('{"ok":true}');
    return;
  }
  handler(req, res);
}).listen(port, "127.0.0.1", () => console.log(`auth service on 127.0.0.1:${port}`));
