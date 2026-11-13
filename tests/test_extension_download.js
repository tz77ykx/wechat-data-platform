const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const selection = { start_date: '2026-09-01', end_date: '2026-09-30', download_mode: 'missing' };

function makeBackground({ urls = [], refreshStatus = 200, refresh = { ok: true }, refreshError, oldServer = false, wrongQueue = false } = {}) {
  const requests = [];
  const progress = [];
  const opened = [];
  const payloads = [];
  const context = vm.createContext({
    URL, URLSearchParams, console, setTimeout, clearTimeout, importScripts() {},
    fetch: async (url, options = {}) => {
      const endpoint = new URL(url).pathname;
      requests.push({ endpoint, method: options.method || 'GET' });
      if (endpoint === '/fetch-msgids') {
        payloads.push(JSON.parse(options.body));
        if (refreshError) throw refreshError;
        return { ok: refreshStatus === 200, status: refreshStatus,
          json: async () => ({ ...refresh, date_range: oldServer ? undefined : JSON.parse(options.body) }) };
      }
      assert.equal(endpoint, '/api/pending-details');
      const query = Object.fromEntries(new URL(url).searchParams);
      payloads.push(query);
      return { ok: true, status: 200, json: async () => ({ ok: true, urls, selection: wrongQueue ? {} : query }) };
    },
    chrome: {
      webRequest: { onBeforeRequest: { addListener() {} } },
      runtime: { onMessage: { addListener() {} } },
      storage: { local: { set(value) { if (value.dl_progress) progress.push(value.dl_progress); } } },
      tabs: {
        create: async ({ url }) => { opened.push(url); return { id: opened.length }; },
        get: async () => ({ windowId: 1 }),
        remove: async () => {},
      },
      scripting: { executeScript: async () => [{ result: { ok: true } }] },
    },
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../chrome_extension/download-selection.js'), 'utf8'), context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../chrome_extension/background.js'), 'utf8'), context);
  vm.runInContext('sleep = async () => {}; waitForTabLoad = async () => {}; waitForNewTabInWindow = async () => null;', context);
  return { requests, progress, opened, payloads,
    run: (selected = selection) => {
      context.testSelection = selected;
      return vm.runInContext('batchDownload(testSelection)', context);
    } };
}

test('refreshes the article list before downloading all 51 pending articles', async () => {
  const urls = Array.from({ length: 51 }, (_, index) => ({
    title: `article-${index}`, publish_date: '2026-09-15', detail_url: `https://mp.weixin.qq.com/detail/${index}`,
  }));
  const background = makeBackground({ urls });
  await background.run();
  assert.deepEqual(background.requests, [
    { endpoint: '/fetch-msgids', method: 'POST' },
    { endpoint: '/api/pending-details', method: 'GET' },
  ]);
  assert.equal(background.opened.length, 51);
  assert.equal(background.progress.at(-1).done, 51);
  assert.deepEqual(background.payloads, [
    { start_date: selection.start_date, end_date: selection.end_date }, selection,
  ]);
});

test('a rejected login stops the batch instead of using the stale pending list', async () => {
  const background = makeBackground({
    urls: [{ title: 'old article', detail_url: 'https://mp.weixin.qq.com/old' }],
    refreshStatus: 500,
    refresh: { ok: false, error: '请求失败：微信接口返回 ret=200040 (invalid csrf token)' },
  });
  await background.run();
  assert.equal(background.requests.length, 1);
  assert.equal(background.requests[0].endpoint, '/fetch-msgids');
  assert.equal(background.opened.length, 0);
  assert.equal(background.progress.at(-1).running, false);
  assert.match(background.progress.at(-1).msg, /invalid csrf token/);
});

test('an application error from list refresh also stops the batch', async () => {
  const background = makeBackground({ refresh: { ok: false, error: '文章列表不可用' } });
  await background.run();
  assert.equal(background.requests.length, 1);
  assert.match(background.progress.at(-1).msg, /文章列表不可用/);
});

test('a refresh connection error never falls back to old articles', async () => {
  const background = makeBackground({ refreshError: new Error('Failed to fetch') });
  await background.run();
  assert.equal(background.requests.length, 1);
  assert.equal(background.requests[0].endpoint, '/fetch-msgids');
  assert.equal(background.opened.length, 0);
  assert.match(background.progress.at(-1).msg, /Failed to fetch/);
});

test('invalid dates stop before any network request', async () => {
  const background = makeBackground();
  await background.run({ ...selection, start_date: '2026-10-01' });
  assert.equal(background.requests.length, 0);
  assert.equal(background.progress.at(-1).error, true);
});

test('an old server that ignores the selected dates cannot cause a full download', async () => {
  const background = makeBackground({ oldServer: true });
  await background.run();
  assert.equal(background.requests.length, 1);
  assert.equal(background.opened.length, 0);
  assert.match(background.progress.at(-1).msg, /尚未应用日期范围/);
});

test('a mismatching download mode stops before opening any article', async () => {
  const background = makeBackground({ wrongQueue: true });
  await background.run();
  assert.equal(background.opened.length, 0);
  assert.match(background.progress.at(-1).msg, /下载范围不一致/);
});

test('an out-of-range article in the response cannot be downloaded', async () => {
  const background = makeBackground({ urls: [{ publish_date: '2026-08-31', detail_url: 'https://mp.weixin.qq.com/old' }] });
  await background.run();
  assert.equal(background.opened.length, 0);
  assert.match(background.progress.at(-1).msg, /日期范围外/);
});

test('refresh mode is forwarded and an empty range is reported accurately', async () => {
  const background = makeBackground();
  await background.run({ ...selection, download_mode: 'refresh' });
  assert.equal(background.payloads[1].download_mode, 'refresh');
  assert.match(background.progress.at(-1).msg, /没有可下载的文章/);
});
