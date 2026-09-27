const test = require('node:test');
const assert = require('node:assert/strict');
const { mkdtemp, rm } = require('node:fs/promises');
const { join } = require('node:path');
const { tmpdir } = require('node:os');
const { createServer } = require('node:http');
const { environment, localURL, protectServer } = require('./runtime.cjs');

test('only exact local origin and its blobs are allowed', () => {
  const origin = 'http://127.0.0.1:12345';
  assert.ok(localURL(origin + '/api/worlds', origin));
  assert.ok(localURL('blob:' + origin + '/abc', origin, true));
  for (const url of ['https://example.org', 'file:///C:/private', 'http://127.0.0.1:12346', origin + '.evil.test', 'javascript:alert(1)']) assert.equal(localURL(url, origin, true), false);
});

test('packaged environment ignores development overrides', async () => {
  const root = await mkdtemp(join(tmpdir(), 'atlas-desktop-test-'));
  try {
    const env = await environment(join(root, 'resources'), join(root, 'data'), {
      ATLAS_CHECKOUT: 'private', ATLAS_RESULT_DIRECTORY: 'private', PYTHONPATH: 'private',
      PROCESSOR_ARCHITECTURE: 'AMD64', SystemRoot: 'C:\\Windows',
    });
    assert.equal(env.PROCESSOR_ARCHITECTURE, 'AMD64');
    assert.equal(env.ATLAS_RESULT_DIRECTORY, undefined);
    assert.equal(env.PYTHONPATH, undefined);
    assert.equal(env.ATLAS_CHECKOUT, join(root, 'resources', 'atlas'));
  } finally { await rm(root, { recursive: true }); }
});

test('untrusted loopback clients never reach backend', async () => {
  let calls = 0;
  const server = createServer((_request, response) => { calls++; response.end('ok'); });
  protectServer(server, 'private-token');
  await new Promise(ok => server.listen(0, '127.0.0.1', ok));
  try {
    const url = `http://127.0.0.1:${server.address().port}`;
    assert.equal((await fetch(url)).status, 403);
    assert.equal(calls, 0);
    assert.equal((await fetch(url, { headers: { 'X-Atlas-Desktop': 'private-token' } })).status, 200);
    assert.equal(calls, 1);
  } finally { await new Promise(ok => server.close(ok)); }
});
