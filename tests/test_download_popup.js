const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

async function makePopup(saved, initialProgress) {
  const html = fs.readFileSync(path.join(__dirname, '../chrome_extension/popup.html'), 'utf8');
  const elements = Object.fromEntries([...html.matchAll(/id="([^"]+)"/g)].map(([, id]) => [id, {
    value: '', textContent: '', className: '', disabled: false, style: {}, handlers: {},
    addEventListener(event, handler) { this.handlers[event] = handler; },
  }]));
  const storage = { download_selection: saved };
  const messages = [];
  const context = vm.createContext({
    document: { getElementById: id => {
      assert.ok(elements[id], `element ${id} exists in popup.html`);
      return elements[id];
    } },
    setInterval: () => 1, clearInterval() {},
    chrome: {
      storage: { local: {
        get: async () => storage,
        set: async value => Object.assign(storage, JSON.parse(JSON.stringify(value))),
      } },
      cookies: { getAll: async () => [] },
      runtime: { sendMessage(message, callback) {
        messages.push(JSON.parse(JSON.stringify(message)));
        callback(message.action === 'start-batch-download' ? { ok: true }
          : message.action === 'get-progress' ? initialProgress : null);
      } },
    },
  });
  for (const file of ['download-selection.js', 'popup.js']) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../chrome_extension', file), 'utf8'), context);
  }
  await vm.runInContext('selectionReady', context);
  return { elements, storage, messages, context,
    change: async (id, value) => { elements[id].value = value; await elements[id].handlers.change(); },
    start: () => elements['btn-download'].handlers.click(),
  };
}

test('popup defaults to the last 30 days and sends the selected bounds and mode', async () => {
  const popup = await makePopup();
  assert.equal(popup.elements['dl-period'].value, '30');
  assert.equal(popup.elements['dl-mode'].value, 'missing');
  const start = popup.elements['dl-start'].value;
  const end = popup.elements['dl-end'].value;
  assert.equal((Date.parse(end) - Date.parse(start)) / 86400000, 29);
  await popup.start();
  assert.deepEqual(popup.messages.at(-1), {
    action: 'start-batch-download',
    selection: { start_date: start, end_date: end, download_mode: 'missing' },
  });
  for (const id of ['dl-period', 'dl-start', 'dl-end', 'dl-mode', 'btn-download']) {
    assert.equal(popup.elements[id].disabled, true);
  }
});

test('custom dates and refresh mode survive reopening the popup', async () => {
  const saved = { preset: 'custom', start_date: '2026-09-01', end_date: '2026-09-30', download_mode: 'refresh' };
  const popup = await makePopup(saved);
  assert.equal(popup.elements['dl-period'].value, 'custom');
  assert.equal(popup.elements['dl-start'].value, saved.start_date);
  assert.equal(popup.elements['dl-end'].value, saved.end_date);
  assert.equal(popup.elements['dl-mode'].value, 'refresh');
  await popup.change('dl-start', '2026-09-10');
  assert.deepEqual(popup.storage.download_selection, { ...saved, start_date: '2026-09-10' });
  await popup.start();
  assert.equal(popup.messages.at(-1).selection.start_date, '2026-09-10');
  assert.equal(popup.messages.at(-1).selection.download_mode, 'refresh');
});

test('editing a preset switches to custom and invalid dates cannot start a batch', async () => {
  const popup = await makePopup();
  await popup.change('dl-start', '9999-12-31');
  assert.equal(popup.elements['dl-period'].value, 'custom');
  await popup.start();
  assert.equal(popup.messages.some(message => message.action === 'start-batch-download'), false);
  assert.match(popup.elements['dl-progress'].textContent, /开始日期不能晚于结束日期/);
  assert.equal(popup.elements['dl-progress'].className, 'err');
  assert.equal(popup.elements['btn-download'].disabled, false);
});

test('reopening during a batch disables range edits and a backend error releases them', async () => {
  const popup = await makePopup(undefined, { running: true, current: 2, total: 5, msg: '下载中' });
  assert.equal(popup.elements['dl-start'].disabled, true);
  vm.runInContext('updateUI({ running: false, error: true, failed: 0, msg: "获取列表失败" })', popup.context);
  assert.equal(popup.elements['dl-start'].disabled, false);
  assert.equal(popup.elements['dl-progress'].className, 'err');
});
