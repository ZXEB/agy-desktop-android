'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { installPhoneFullscreen, phoneWindowMode } = require('../tools/runtime/codex-workspace-provider.cjs');

function window(url = 'app://-/index.html', parent = null, visible = true) {
  const win = new EventEmitter();
  const contents = new EventEmitter();
  Object.assign(contents, { url, getURL() { return this.url; }, isDestroyed: () => false });
  return Object.assign(win, {
    webContents: contents, destroyed: false, fullscreen: false, visible, calls: [],
    isDestroyed() { return this.destroyed; }, getParentWindow: () => parent, isModal: () => false,
    isVisible() { return this.visible; }, isMinimized: () => false, isFullScreenable: () => true,
    isFullScreen() { return this.fullscreen; },
    setFullScreen(value) { this.calls.push(value); this.fullscreen = value; this.emit('enter-full-screen'); },
  });
}
function runtime(windows = [], ready = true) {
  return { app: Object.assign(new EventEmitter(), { isReady: () => ready }),
    BrowserWindow: { getAllWindows: () => windows } };
}
const phone = { CODEX_PHONE_CLIENT_COMPAT: '1' };
const settled = () => new Promise(resolve => setImmediate(resolve));

test('phone onboarding uses normal geometry without changing the requested content', () => {
  const mode = Object.freeze({ mode: 'onboarding', onboardingVariant: 'v2' });
  assert.deepEqual(phoneWindowMode(mode, phone), { mode: 'app', onboardingVariant: 'v2' });
  assert.equal(phoneWindowMode(mode, {}), mode);
  const normal = { mode: 'app' };
  assert.equal(phoneWindowMode(normal, phone), normal);
});

test('phone startup enters F11 mode once and respects a later manual exit', async () => {
  const win = window();
  installPhoneFullscreen(runtime([win]), phone);
  await settled();
  assert.deepEqual(win.calls, [true]);
  win.fullscreen = false; // The person presses F11.
  win.emit('ready-to-show'); win.webContents.emit('did-finish-load');
  assert.equal(win.fullscreen, false);
  assert.deepEqual(win.calls, [true]);
});
test('waits for the main document and handles windows created after startup', async () => {
  const electron = runtime();
  installPhoneFullscreen(electron, phone);
  const win = window('about:blank');
  electron.app.emit('browser-window-created', {}, win);
  assert.deepEqual(win.calls, []);
  win.webContents.url = 'app://-/index.html?locale=zh-CN#home';
  win.webContents.emit('did-finish-load');
  win.emit('ready-to-show');
  await settled();
  assert.deepEqual(win.calls, [true]);
});
test('does not fullscreen auth, embedded browser, devtools or child dialogs', async () => {
  const windows = [window('https://auth.openai.com/'), window('https://example.com/'),
    window('devtools://devtools/'), window('app://-/index.html', {})];
  installPhoneFullscreen(runtime(windows), phone);
  await settled();
  windows.forEach(win => assert.deepEqual(win.calls, []));
});
test('does not change the non-phone profile', () => {
  const win = window(), electron = runtime([win]);
  assert.equal(installPhoneFullscreen(electron, {}), false);
  assert.equal(electron.app.listenerCount('browser-window-created'), 0);
  assert.deepEqual(win.calls, []);
});
test('registers only once, including when loaded before Electron is ready', async () => {
  const win = window(), electron = runtime([win], false);
  installPhoneFullscreen(electron, phone);
  installPhoneFullscreen(electron, phone);
  assert.deepEqual(win.calls, []);
  electron.app.emit('ready');
  await settled();
  assert.deepEqual(win.calls, [true]);
  assert.equal(electron.app.listenerCount('browser-window-created'), 1);
});
test('a closed or destroyed window is never changed by a delayed load', async () => {
  const win = window('about:blank'), electron = runtime([win]);
  installPhoneFullscreen(electron, phone);
  win.destroyed = true; win.emit('closed');
  win.webContents.url = 'app://-/index.html';
  win.webContents.emit('did-finish-load');
  await settled();
  assert.deepEqual(win.calls, []);
});

test('waits until a hidden startup window is shown and restored maximization has run', async () => {
  const win = window('app://-/index.html', null, false);
  installPhoneFullscreen(runtime([win]), phone);
  win.emit('ready-to-show');
  win.webContents.emit('did-finish-load');
  await settled();
  assert.deepEqual(win.calls, []);
  // The upstream show listener restores the saved window state.
  win.once('show', () => { win.fullscreen = false; });
  win.visible = true;
  win.emit('show');
  await settled();
  assert.equal(win.fullscreen, true);
  assert.deepEqual(win.calls, [true]);
});

test('an unacknowledged X11 request is retried when the window receives focus', async () => {
  const win = window();
  const setFullScreen = win.setFullScreen;
  win.setFullScreen = value => { win.calls.push(value); };
  installPhoneFullscreen(runtime([win]), phone);
  await settled();
  assert.equal(win.fullscreen, false);
  win.setFullScreen = setFullScreen;
  win.emit('focus');
  await settled();
  assert.equal(win.fullscreen, true);
  assert.deepEqual(win.calls, [true, true]);
  win.fullscreen = false;
  win.emit('focus');
  await settled();
  assert.equal(win.fullscreen, false);
});

test('navigation or destruction between show and the deferred request cancels it', async () => {
  const changed = window(), closed = window();
  installPhoneFullscreen(runtime([changed, closed]), phone);
  changed.webContents.url = 'https://example.com/';
  closed.destroyed = true;
  closed.emit('closed');
  await settled();
  assert.deepEqual(changed.calls, []);
  assert.deepEqual(closed.calls, []);
});

test('a fullscreen-disabled startup or overlay window is left alone', async () => {
  const win = window();
  win.isFullScreenable = () => false;
  installPhoneFullscreen(runtime([win]), phone);
  await settled();
  assert.deepEqual(win.calls, []);
});
