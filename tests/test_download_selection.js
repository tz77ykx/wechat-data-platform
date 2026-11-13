const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const context = vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../chrome_extension/download-selection.js'), 'utf8'), context);
const selection = vm.runInContext('DownloadSelection', context);

test('default selection is the latest 30 inclusive days in China with missing-only mode', () => {
  const result = selection.resolve({}, new Date('2026-10-12T16:30:00Z'));
  assert.deepEqual(JSON.parse(JSON.stringify(result)), {
    preset: '30', start_date: '2026-09-14', end_date: '2026-10-13', download_mode: 'missing',
  });
});

test('relative dates roll forward instead of reusing previously saved dates', () => {
  const result = selection.resolve({ preset: '7', start_date: '2025-01-01', end_date: '2025-01-07' }, new Date('2026-01-02T00:00:00Z'));
  assert.equal(result.start_date, '2025-12-27');
  assert.equal(result.end_date, '2026-01-02');
});

test('custom ranges and refresh preference survive reopening', () => {
  const stored = { preset: 'custom', start_date: '2025-01-01', end_date: '2025-01-31', download_mode: 'refresh' };
  assert.deepEqual(JSON.parse(JSON.stringify(selection.resolve(stored))), stored);
});

test('date validation rejects invalid calendar days, inverted ranges and unknown modes', () => {
  const base = { start_date: '2026-02-01', end_date: '2026-02-28', download_mode: 'missing' };
  assert.throws(() => selection.validate({ ...base, end_date: '2026-02-30' }));
  assert.throws(() => selection.validate({ ...base, end_date: '2026-01-01' }));
  assert.throws(() => selection.validate({ ...base, download_mode: 'all' }));
  assert.throws(() => selection.validate());
  assert.equal(selection.validate({ ...base, start_date: '2024-02-29' }).start_date, '2024-02-29');
});
