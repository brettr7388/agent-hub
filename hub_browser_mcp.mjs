// Route only the Hub-owned sentinel WebSocket endpoint to the private Unix socket.
// Usage: node hub_browser_mcp.mjs SOCKET_PATH INSTALLED_MCP_SCRIPT [safe MCP flags]
import http from 'node:http';
import {syncBuiltinESMExports} from 'node:module';
import {pathToFileURL} from 'node:url';
import fs from 'node:fs';
import path from 'node:path';

const [socketPath, script, ...extra] = process.argv.slice(2);
if (!socketPath || !script) throw new Error('Socket path and installed MCP script required');
const parent = socketPath.substring(0, socketPath.lastIndexOf('/'));
if (!path.isAbsolute(socketPath)) throw new Error('Unsafe Pip browser socket path');
let part = path.parse(parent).root;
for (const component of parent.slice(part.length).split(path.sep).filter(Boolean)) {
  part = path.join(part, component);
  if (fs.lstatSync(part).isSymbolicLink()) throw new Error('Unsafe Pip browser socket directory');
}
const dir = fs.lstatSync(parent);
const endpoint = fs.lstatSync(socketPath);
if (!dir.isDirectory() || (dir.mode & 0o777) !== 0o700 || dir.uid !== process.getuid() ||
    !endpoint.isSocket() || (endpoint.mode & 0o777) !== 0o600 || endpoint.uid !== process.getuid()) {
  throw new Error('Unsafe Pip browser socket');
}
const forbidden = /^--(?:browser-?url|ws-?endpoint|ws-?headers|channel|user-?data-?dir|auto-?connect|executable-?path|chrome-?args?|ignore-?default-?chrome-?args)(?:=|$)/i;
if (extra.some(flag => forbidden.test(flag))) throw new Error('Browser targeting flags are Hub-owned');

const originalRequest = http.request;
const sentinel = 'ws://127.0.0.1:9/devtools/browser/pip';
function targetOptions(input, options) {
  const url = typeof input === 'string' || input instanceof URL ? new URL(input) : null;
  const merged = {...(url ? {
    protocol: url.protocol === 'ws:' ? 'http:' : url.protocol,
    hostname: url.hostname,
    port: url.port,
    path: url.pathname + url.search,
  } : input), ...(options || {})};
  const host = merged.hostname || merged.host;
  const port = String(merged.port || '80');
  const path = merged.path || merged.pathname || '/';
  if (host !== '127.0.0.1' || port !== '9' || path !== '/devtools/browser/pip') return null;
  // socketPath is the only transport. An inherited proxy/agent cannot reroute it.
  delete merged.host;
  delete merged.hostname;
  delete merged.port;
  delete merged.protocol;
  delete merged.agent;
  delete merged.createConnection;
  return {...merged, socketPath, path, agent: false};
}
http.request = function (...args) {
  let callback;
  if (typeof args.at(-1) === 'function') callback = args.pop();
  const rewritten = targetOptions(args[0], args[1]);
  if (!rewritten) return originalRequest.apply(this, callback ? [...args, callback] : args);
  return originalRequest.call(this, rewritten, callback);
};
syncBuiltinESMExports();

// Puppeteer sees this as a normal browser WebSocket endpoint. The MCP server is
// imported in-process; no npx, second Chrome, or TCP listener is launched.
process.env.CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS = '1';
process.argv = [process.execPath, script, '--wsEndpoint=' + sentinel,
  '--no-usage-statistics', ...extra];
await import(pathToFileURL(script).href);
