// Service Worker — 公众号数据分析 PWA
const CACHE = 'wechat-analytics-v1';
const STATIC = [
  'https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js',
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(STATIC)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// 网络优先，失败时读缓存（仅对 CDN 静态资源）
self.addEventListener('fetch', e => {
  if (!e.request.url.startsWith('http')) return;
  // API 请求不缓存，始终走网络
  if (e.request.url.includes('/api/')) return;
  e.respondWith(
    fetch(e.request).catch(() => caches.match(e.request))
  );
});
