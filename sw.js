/* STEM Line Designer — Service Worker
   アプリのシェルをキャッシュしてオフライン起動を可能にする。
   MediaPipeのCDNや解析はオンライン必須だが、UIの起動自体は速くなる。
   更新時は CACHE 名のバージョンを上げること（例: stem-v2）。*/
const CACHE = 'stem-v9';
const ASSETS = [
  './',
  './index.html',
  './manifest.webmanifest',
  './icon-180.png',
  './icon-192.png',
  './icon-512.png',
  './icon-512-maskable.png'
];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  // 同一オリジンのアセットのみ扱う（CDN/APIは常にネットワークへ）
  if (url.origin !== location.origin) return;
  // ネットワーク優先・失敗時キャッシュ（常に最新HTMLを取りつつオフラインでも起動）
  e.respondWith(
    fetch(e.request)
      .then(res => {
        const copy = res.clone();
        caches.open(CACHE).then(c => c.put(e.request, copy)).catch(() => {});
        return res;
      })
      .catch(() => caches.match(e.request).then(r => r || caches.match('./index.html')))
  );
});
