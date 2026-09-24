const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

function scope() {
  const elements = new Map();
  const images = [];
  const timers = [];
  let now = 1000;
  function element(id) {
    if (!elements.has(id)) {
      const classes = new Set();
      elements.set(id, {
        textContent: '', value: '', dataset: {}, style: {}, children: [],
        classList: {
          toggle(name, on) { if (on) classes.add(name); else classes.delete(name); },
          contains(name) { return classes.has(name); },
          add(name) { classes.add(name); }, remove(name) { classes.delete(name); },
        },
        setAttribute(name, value) { this[name] = value; },
        appendChild(child) { this.children.push(child); },
        getContext() { return {}; },
      });
    }
    return elements.get(id);
  }
  const context = vm.createContext({
    document: { getElementById: element, querySelector: () => element('switch'), createElement: () => element(Symbol()) },
    window: {}, performance: { now: () => now },
    Image: class { constructor() { images.push(this); } },
    setInterval(fn) { timers.push(fn); }, setTimeout() {},
    recomputeLayout() {}, draw() {}, navigator: { clipboard: { writeText() {} } },
  });
  for (const file of ['state.js', 'helpers.js', 'events.js', 'handlers.js']) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../apps/web/scope/js', file), 'utf8'), context, { filename: file });
  }
  return {
    context, element, images,
    run(code) { return vm.runInContext(code, context); },
    event(type, data) { context.window.__recv(JSON.stringify({ type, data })); },
    frame() { context.window.__recvFrame('data:image/jpeg;base64,test', 640, 480); },
    advance(ms) { now += ms; timers.forEach(fn => fn()); },
  };
}

test('connection status uses backend confirmation, never frame or capture failures', () => {
  const s = scope();
  s.event('device_status', { connected: true, serial: 'emulator-5554' });
  assert.match(s.element('device-state').textContent, /Connected.*emulator-5554/);
  s.event('capture_failed', { error: 'decoder unavailable' });
  assert.match(s.element('device-state').textContent, /Connected/);
  assert.match(s.element('operation-state').textContent, /Capture failed: decoder unavailable/);
  s.event('device_status', { connected: false, serial: 'emulator-5554' });
  assert.match(s.element('device-state').textContent, /Disconnected/);
  assert.equal(s.run('S.connectedSerial'), null);
  s.frame(); s.images[0].onload();
  assert.match(s.element('device-state').textContent, /Disconnected/);
});

test('only a decoded frame establishes age; stale means overdue auto capture, not disconnected', () => {
  const s = scope();
  s.event('captured', { w: 640, h: 480 });
  assert.equal(s.run('S.lastFrameAt'), null);
  s.frame(); s.advance(600); s.images[0].onload();
  assert.equal(s.run('S.lastFrameAt'), 1000);
  s.advance(11000);
  assert.match(s.element('capture-state').textContent, /Stale/);
  assert.equal(s.element('device-state').textContent, '');
  s.event('auto_refresh', { enabled: false });
  assert.match(s.element('capture-state').textContent, /Held/);
  s.advance(3000);
  assert.match(s.element('capture-state').textContent, /Held/);
  assert.match(s.element('capture-age').textContent, /14 s since receipt/);
});

test('slower capture rates allow three intervals before marking overdue', () => {
  const s = scope();
  s.run('S.refreshHz=0.2');
  s.frame(); s.images[0].onload(); s.advance(11000);
  assert.doesNotMatch(s.element('capture-state').textContent, /Stale/);
  s.advance(5000);
  assert.match(s.element('capture-state').textContent, /Stale/);
});

test('late image decoding cannot replace newer frame or hide operation failure', () => {
  const s = scope();
  s.frame(); const older = s.images[0];
  s.advance(100); s.frame(); const newer = s.images[1];
  newer.onload(); older.onload();
  assert.equal(s.run('S.img'), newer);
  s.event('capture_failed', { error: 'decoder unavailable' });
  s.event('captured', { w: 640, h: 480 });
  assert.match(s.element('operation-state').textContent, /Capture failed/);
  assert.match(s.element('capture-state').textContent, /Frame/);
});

test('device selection awaits backend confirmation and failures never imply disconnect', async () => {
  const s = scope();
  s.event('device_status', { connected: true, serial: 'old' });
  s.context.window.pywebview = { api: { select_device: async () => true } };
  await s.run('onDeviceChange("new")');
  assert.match(s.element('device-state').textContent, /Connecting.*new/);
  assert.equal(s.run('S.connectedSerial'), null);
  s.event('device_status', { connected: true, serial: 'new' });
  s.event('log', { ts: '12:00', level: 'error', msg: 'Tap failed at (3, 4)' });
  assert.match(s.element('operation-state').textContent, /Tap failed/);
  assert.match(s.element('device-state').textContent, /Connected.*new/);
  s.frame(); s.images[0].onload();
  assert.match(s.element('operation-state').textContent, /Tap failed/);
});

test('selection readout reflects actual region, point and backend clear', async () => {
  const s = scope();
  s.context.window.pywebview = { api: { set_region: async () => ({}) } };
  for (const [id, value] of [['rg-x','10'], ['rg-y','20'], ['rg-w','30'], ['rg-h','40']]) s.element(id).value=value;
  await s.run('onApplyRegion()');
  assert.match(s.element('selection-state').textContent, /10,20.*30×40/);
  s.event('selection_cleared', {});
  assert.equal(s.element('selection-state').textContent, 'No selection');
  s.run('S.point=[7,8]; setRegionBadge(false)');
  assert.match(s.element('selection-state').textContent, /Point.*7.*8/);
});

test('capture rejection or decode error does not fabricate a new frame', async () => {
  const s = scope();
  s.context.window.pywebview = { api: { capture: async () => { throw Error('bridge failed'); } } };
  await s.run('onCapture()');
  assert.match(s.element('operation-state').textContent, /Capture failed: bridge failed/);
  assert.equal(s.run('S.capturePending'), false);
  s.frame(); s.images[0].onerror();
  assert.equal(s.run('S.lastFrameAt'), null);
  assert.match(s.element('operation-state').textContent, /decode/i);
});

test('configured backend is not reported as image provenance, and backend updates render', async () => {
  const s = scope();
  s.event('capture_backend', { backend: 'adb' });
  assert.match(s.element('capture-source-state').textContent, /Configured.*ADB screencap/);
  s.context.window.pywebview = { api: { set_capture_backend: async () => ({ backend: 'scrcpy' }) } };
  await s.run('onCaptureBackendChange("scrcpy")');
  assert.match(s.element('capture-source-state').textContent, /Configured.*scrcpy/);
});

test('manual capture waits for decoded image, preserves failure and handles declined requests', async () => {
  const s = scope();
  s.context.window.pywebview = { api: { capture: async () => true } };
  await s.run('onCapture()');
  assert.match(s.element('operation-state').textContent, /requested/);
  s.event('captured', { w: 640, h: 480 });
  assert.match(s.element('operation-state').textContent, /requested/);
  s.frame(); s.images[0].onload();
  assert.match(s.element('operation-state').textContent, /Frame displayed/);
  s.context.window.pywebview.api.capture=async () => false;
  await s.run('onCapture()');
  assert.match(s.element('operation-state').textContent, /not started/);
  assert.equal(s.run('S.capturePending'), false);
});

test('initial hydration renders backend connection and configuration without waiting for polling', async () => {
  const s = scope();
  s.context.document.readyState='loading';
  s.context.document.addEventListener=() => {};
  s.context.resizeCanvas=() => {};
  s.element('ocr-backend').options=[];
  s.context.window.pywebview = { api: { get_state: async () => ({
    connectedSerial: 'emulator-5554', captureBackend: 'adb', captureBackends: ['adb'],
    autoRefresh: false, refreshHz: 0.2, ocrModels: [], log: [],
  }) } };
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../apps/web/scope/js/init.js'), 'utf8'), s.context);
  await s.run('init()');
  assert.match(s.element('device-state').textContent, /Connected.*emulator-5554/);
  assert.match(s.element('capture-source-state').textContent, /Configured.*ADB/);
  assert.equal(s.run('S.lastFrameAt'), null);
});

test('match and color results expose actual response, including zero hits and failures', async () => {
  const s = scope();
  s.context.window.pywebview = { api: {
    match_template: async () => ({ summary: '0 matches', rects: [] }),
    check_color: async () => ({ error: 'Capture first' }),
  } };
  await s.run('onRunMatch(true)');
  assert.match(s.element('operation-state').textContent, /0 matches/);
  await s.run('onCheckColor()');
  assert.match(s.element('operation-state').textContent, /Capture first/);
  assert.equal(s.element('operation-state').dataset.state, 'failed');
});

test('pending device selection clears connection dots and declined selection stops pending', async () => {
  const s = scope();
  s.event('device_status', { connected: true, serial: 'old' });
  let resolve;
  s.context.window.pywebview={api:{select_device:()=>new Promise(r=>resolve=r)}};
  const selecting=s.run('onDeviceChange("new")');
  assert.equal(s.element('device-dot').classList.contains('connected'), false);
  resolve(false); await selecting;
  assert.doesNotMatch(s.element('device-state').textContent, /Connecting/);
  assert.match(s.element('operation-state').textContent, /selection.*failed/i);
});