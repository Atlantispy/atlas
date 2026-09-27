'use strict';
const { join } = require('node:path');
const { mkdir, lstat, realpath } = require('node:fs/promises');

async function plainDirectory(path) {
  await mkdir(path, { recursive: true });
  if (!(await lstat(path)).isDirectory() || (await lstat(path)).isSymbolicLink()
      || (await realpath(path)).toLowerCase() !== path.toLowerCase()) {
    throw new Error('Atlas storage must be a plain local directory.');
  }
}

async function environment(resources, userData, inherited = process.env) {
  // No development checkout, Python, job-root or saved-result overrides leak in.
  const env = {};
  for (const key of ['SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'PROCESSOR_ARCHITECTURE', 'PROCESSOR_ARCHITEW6432']) {
    const original = Object.keys(inherited).find(k => k.toUpperCase() === key);
    if (original) env[key] = inherited[original];
  }
  Object.assign(env, {
    ATLAS_READER_PYTHON: join(resources, 'python', 'python.exe'),
    ATLAS_CHECKOUT: join(resources, 'atlas'),
    ATLAS_WORLDS_ROOT: join(userData, 'worlds'),
    ATLAS_JOBS_ROOT: join(userData, 'column-jobs'),
    ATLAS_EVOLUTION_JOBS_ROOT: join(userData, 'regional-jobs'),
  });
  for (const key of ['ATLAS_WORLDS_ROOT', 'ATLAS_JOBS_ROOT', 'ATLAS_EVOLUTION_JOBS_ROOT']) await plainDirectory(env[key]);
  return env;
}

function localURL(value, origin, blobs = false) {
  try { const url = new URL(value); return (url.protocol === 'http:' && url.origin === origin)
    || (blobs && url.protocol === 'blob:' && url.origin === origin); }
  catch { return false; }
}

function protectServer(server, token) {
  const handlers = server.listeners('request');
  server.removeAllListeners('request');
  server.on('request', (request, response) => {
    if (request.headers['x-atlas-desktop'] !== token) {
      response.writeHead(403, { 'Content-Type': 'text/plain' });
      response.end('Use the Atlas desktop window.');
      return;
    }
    for (const handler of handlers) handler.call(server, request, response);
  });
}
module.exports = { environment, localURL, protectServer, plainDirectory };
