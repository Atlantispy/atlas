import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { join, resolve } from 'node:path';
const version = '44.4.5';
const digest = '11c395820a5aaa8ebcc0686b476d0ac98a730274ebfbdc8cf5538a7c2815cb5d';
const root = resolve(process.argv[2]);
await mkdir(root, { recursive: true });
const path = join(root, `electron-v${version}-win32-x64.zip`);
let bytes = await readFile(path).catch(error => { if (error.code !== 'ENOENT') throw error; });
if (!bytes) {
  const response = await fetch(`https://github.com/electron/electron/releases/download/v${version}/electron-v${version}-win32-x64.zip`);
  if (!response.ok) throw new Error(`Download failed: ${response.status}`);
  bytes = Buffer.from(await response.arrayBuffer());
  if (createHash('sha256').update(bytes).digest('hex') !== digest) throw new Error('Electron archive checksum mismatch.');
  await writeFile(path, bytes, { flag: 'wx' });
}
if (createHash('sha256').update(bytes).digest('hex') !== digest) throw new Error('Cached Electron checksum mismatch.');
console.log(JSON.stringify({ version, sha256: digest, bytes: bytes.length, file: path }));
