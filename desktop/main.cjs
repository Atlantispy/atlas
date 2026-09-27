'use strict';
const { app, BrowserWindow, Menu, dialog, session } = require('electron');
const { join, resolve } = require('node:path');
const { pathToFileURL } = require('node:url');
const { mkdir, readFile, writeFile, appendFile } = require('node:fs/promises');
const { randomBytes } = require('node:crypto');
const { environment, localURL, protectServer, plainDirectory } = require('./runtime.cjs');

app.setName('Atlas');
const smokeAt = process.argv.indexOf('--smoke-test');
const smokeRoot = smokeAt < 0 ? null : resolve(process.argv[smokeAt + 1] || '.');
const userData = smokeRoot ? join(smokeRoot, 'profile') : join(app.getPath('appData'), 'Atlas');
app.setPath('userData', userData);
app.enableSandbox();
let window, server, closing = false, exiting = false;
let exitCode = 0;
const log = async message => {
  await mkdir(userData, { recursive: true });
  await appendFile(join(userData, 'desktop.log'), `${new Date().toISOString()} ${message}\n`).catch(() => {});
};

async function shutdown() {
  if (closing) return;
  closing = true;
  window?.setTitle('Atlas — closing calculations…');
  try {
    if (server) await new Promise((ok, fail) => {
      server.close(error => error ? fail(error) : ok());
      server.closeAllConnections();
    });
  } catch (error) { exitCode = 1; await log(`Shutdown failed: ${error.stack}`); }
  exiting = true;
  window?.destroy();
  app.exit(exitCode);
}

app.on('before-quit', event => {
  if (!exiting) { event.preventDefault(); if (window && !closing) window.close(); else void shutdown(); }
});
app.on('window-all-closed', () => { void shutdown(); });
if (!app.requestSingleInstanceLock()) { exiting = true; app.quit(); }
else {
  app.on('second-instance', () => { if (window) { if (window.isMinimized()) window.restore(); window.show(); window.focus(); } });
  app.whenReady().then(async () => {
    await plainDirectory(userData);
    const resources = process.resourcesPath;
    const env = await environment(resources, userData);
    const { createAtlasServer } = await import(pathToFileURL(join(__dirname, 'ui', 'serve.mjs')).href);
    server = await createAtlasServer({ env, assetRoot: join(__dirname, 'ui') });
    const token = randomBytes(32).toString('hex');
    protectServer(server, token);
    // Preserve the origin between launches so browser-backed draft storage persists.
    let port = 0;
    const portFile = join(userData, 'desktop-port.json');
    try {
      port = JSON.parse(await readFile(portFile, 'utf8')).port;
      if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('Invalid saved desktop port.');
    } catch (error) { if (error.code !== 'ENOENT') throw error; }
    await new Promise((ok, fail) => { server.once('error', fail); server.listen(port, '127.0.0.1', ok); });
    port = server.address().port;
    if (!await readFile(portFile).catch(() => null)) await writeFile(portFile, JSON.stringify({ port }), { flag: 'wx' });
    const origin = `http://127.0.0.1:${port}`;
    const ses = session.defaultSession;
    ses.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
    ses.setPermissionCheckHandler(() => false);
    ses.webRequest.onBeforeRequest((details, callback) => callback({ cancel: !localURL(details.url, origin, true) }));
    ses.webRequest.onBeforeSendHeaders((details, callback) => {
      if (localURL(details.url, origin)) details.requestHeaders['X-Atlas-Desktop'] = token;
      callback({ requestHeaders: details.requestHeaders });
    });
    ses.on('will-download', (event, item) => {
      if (!localURL(item.getURL(), origin, true)) event.preventDefault();
      // Electron's native Save As dialogue remains the user's file authority.
    });
    window = new BrowserWindow({ width: 1480, height: 980, minWidth: 1024, minHeight: 720,
      title: 'Atlas', backgroundColor: '#17212d', show: false,
      webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true,
        webSecurity: true, webviewTag: false, spellcheck: false } });
    window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    window.webContents.on('will-navigate', (event, url) => { if (!localURL(url, origin)) event.preventDefault(); });
    window.webContents.on('will-attach-webview', event => event.preventDefault());
    let rejectRenderer;
    const rendererFailure = new Promise((_resolve, reject) => { rejectRenderer = reject; });
    window.webContents.on('render-process-gone', (_event, detail) => {
      const error = new Error(`Atlas renderer stopped: ${detail.reason} (exit ${detail.exitCode}).`);
      void log(error.message);
      rejectRenderer(error);
    });
    window.webContents.on('will-prevent-unload', event => {
      const choice = dialog.showMessageBoxSync(window, { type: 'question',
        buttons: ['Keep Atlas open', 'Close without saving'], defaultId: 0, cancelId: 0,
        title: 'Unsaved changes', message: 'Keep Atlas open to save your changes?' });
      if (choice === 1) event.preventDefault(); // Electron: allow the requested unload.
    });
    window.on('closed', () => { window = null; });
    Menu.setApplicationMenu(Menu.buildFromTemplate([
      { label: 'File', submenu: [{ label: 'Exit', accelerator: 'Alt+F4', click: () => app.quit() }] },
      { label: 'View', submenu: [{ role: 'resetZoom' }, { role: 'zoomIn' }, { role: 'zoomOut' }, { role: 'togglefullscreen' }] },
      { label: 'Help', submenu: [{ label: 'About Atlas', click: () => dialog.showMessageBox(window, {
        title: 'Atlas', message: 'Atlas — Tectonics development build',
        detail: 'A local, physically informed worldbuilding tool. Uses the current experimental tectonics route.\n\nSave World exports a portable .atlas file; Load World reopens it. Closing Atlas cancels active work without deleting saved worlds.\n\nAGPL-3.0-only. Python and third-party notices are included with this application.' }) }] },
    ]));
    let loadTimeout;
    try {
      await Promise.race([window.loadURL(origin), rendererFailure,
        new Promise((_ok, fail) => { loadTimeout = setTimeout(() => fail(new Error('Atlas window startup timed out.')), 30000); })]);
    } finally { clearTimeout(loadTimeout); }
    await log(`Started Atlas ${app.getVersion()}`);
    if (smokeRoot) {
      try { await require('./smoke.cjs').run({ window, server, origin, token, smokeRoot, resources }); }
      catch (error) { exitCode = 1; await log(error.stack); await writeFile(join(smokeRoot, 'failure.txt'), String(error.stack), { flag: 'wx' }); }
      await shutdown();
    } else window.show();
  }).catch(async error => {
    exitCode = 1;
    await log(error.stack);
    if (!smokeRoot) dialog.showErrorBox('Atlas could not start', `${error.message}\n\nDetails: ${join(userData, 'desktop.log')}`);
    else await writeFile(join(smokeRoot, 'failure.txt'), String(error.stack), { flag: 'wx' }).catch(() => {});
    await shutdown();
  });
}
