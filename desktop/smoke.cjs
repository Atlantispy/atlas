'use strict';
// Explicit opt-in development acceptance, isolated from the normal profile.
const assert = require('node:assert/strict');
const { writeFile, readFile, stat } = require('node:fs/promises');
const { join } = require('node:path');
const { createHash } = require('node:crypto');

async function waitFor(window, expression, timeout = 60000) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    if (await window.webContents.executeJavaScript(expression)) return;
    await new Promise(ok => setTimeout(ok, 250));
  }
  throw new Error('Desktop UI did not reach expected state: ' + expression);
}

async function run({ window, origin, token, smokeRoot, resources }) {
  const start = performance.now();
  const report = { schema: 'atlas.desktop-smoke.v1', status: 'RUNNING', checks: [], resources_bundled: true };
  const note = value => report.checks.push(value);
  await waitFor(window, "!!document.querySelector('[data-action=world-new]')");
  note('Renderer and New World control loaded');
  const globals = await window.webContents.executeJavaScript("({require:typeof require,process:typeof process})");
  assert.deepEqual(globals, { require: 'undefined', process: 'undefined' });
  note('Renderer has no Node access');
  const previous = await readFile(join(smokeRoot, 'report.json'), 'utf8').catch(() => null);
  if (previous) {
    await waitFor(window, "document.querySelector('.world-name')?.textContent.includes('Desktop smoke')");
    assert.equal(origin, JSON.parse(previous).origin);
    note('Second process restored the same origin, profile and saved native world');
    report.origin = origin;
    report.status = 'PASS';
    report.elapsed_seconds = (performance.now() - start) / 1000;
    await writeFile(join(smokeRoot, 'reopen-report.json'), JSON.stringify(report, null, 2), { flag: 'wx' });
    return;
  }
  const headers = { 'X-Atlas-Desktop': token, Origin: origin };
  const json = async (path, init = {}) => {
    const response = await fetch(origin + path, { ...init, headers: { ...headers, ...init.headers } });
    const value = await response.json();
    assert.equal(response.status, 200, JSON.stringify(value));
    return value;
  };
  assert.equal((await fetch(origin + '/api/new-world/describe')).status, 403);
  note('Unauthorised loopback client refused');
  await json('/api/new-world/describe');
  await json('/api/tectonics/jobs/capabilities');
  note('Bundled Python configuration and job capabilities available');
  const request = { schema: 'atlas.new-world-request.v1', seed: '00000000000000000000000000000029',
    recipe: 'atlas-initial-contract-v1', mode: 'statistical-kinematic',
    epoch: { id: 'initial-epoch', time_s: 0 },
    frame: { id: 'world-frame', coordinate_system: 'planet-centred-cartesian', length_unit: 'm', vertical_reference: 'radial-depth-below-reference-sphere' },
    settings: { radius_m: { mode: 'fixed', value: 6371000 }, gravity_m_s2: { mode: 'fixed', value: 9.81 },
      plate_count: { mode: 'fixed', value: 6 }, continental_fraction: { mode: 'fixed', value: 0.3 } },
    resolution: { support_cells: 192 }, resources: { max_work_bytes: 128 << 20, max_wall_seconds: 30 } };
  const created = await json('/api/worlds/new', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: 'Desktop smoke', request }) });
  assert.equal(created.world.title, 'Desktop smoke');
  note('Real native seeded world created: seed41, six plates, 192 support cells');
  const response = await fetch(`${origin}/api/worlds/${created.token}/download`, { headers });
  assert.equal(response.status, 200);
  const bytes = Buffer.from(await response.arrayBuffer());
  const file = join(smokeRoot, 'smoke-world.atlas');
  await writeFile(file, bytes, { flag: 'wx' });
  report.project_bytes = bytes.length;
  report.project_sha256 = createHash('sha256').update(bytes).digest('hex');
  note('Native project archive exported');
  // Exercise the real Load World HTML file input, not a replacement renderer.
  window.webContents.debugger.attach('1.3');
  try {
    const { root } = await window.webContents.debugger.sendCommand('DOM.getDocument');
    const { nodeId } = await window.webContents.debugger.sendCommand('DOM.querySelector', { nodeId: root.nodeId, selector: '#load-world' });
    await window.webContents.debugger.sendCommand('DOM.setFileInputFiles', { nodeId, files: [file] });
  } finally { window.webContents.debugger.detach(); }
  await waitFor(window, "document.querySelector('.world-name')?.textContent.includes('Desktop smoke')");
  note('Load World file-input path displayed the real saved world');
  const savedFile = join(smokeRoot, 'saved-by-button.atlas');
  const downloaded = new Promise((ok, fail) => {
    const timeout = setTimeout(() => fail(new Error('Save World download timed out.')), 60000);
    window.webContents.session.once('will-download', (_event, item) => {
      item.setSavePath(savedFile);
      item.once('done', (_event, state) => { clearTimeout(timeout); state === 'completed' ? ok() : fail(new Error('Download ' + state)); });
    });
  });
  await window.webContents.executeJavaScript("document.querySelector('[data-action=world-save]').click()");
  await downloaded;
  const savedBytes = await readFile(savedFile);
  assert.ok(savedBytes.length > 0);
  const reopened = await json('/api/worlds/load', { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: savedBytes });
  assert.deepEqual(reopened.world, created.world);
  note('Save World button produced an archive; native reload preserved every world-view field');
  await window.webContents.executeJavaScript("document.querySelector('[data-action=show-world]')?.click()");
  await new Promise(ok => setTimeout(ok, 300));
  const screenshot = await window.webContents.capturePage();
  await writeFile(join(smokeRoot, 'desktop.png'), screenshot.toPNG(), { flag: 'wx' });
  report.screenshot_bytes = (await stat(join(smokeRoot, 'desktop.png'))).size;
  report.origin = origin;
  report.status = 'PASS';
  report.elapsed_seconds = (performance.now() - start) / 1000;
  await writeFile(join(smokeRoot, 'report.json'), JSON.stringify(report, null, 2), { flag: 'wx' });
}
module.exports = { run };
