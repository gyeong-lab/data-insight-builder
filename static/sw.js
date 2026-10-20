const CACHE_NAME = 'data-insight-v1';
const PRECACHE_ASSETS = [
  '/',
  '/static/style.css',
  '/static/app.js',
  '/static/manifest.json',
  '/static/icon-192.png',
  '/static/icon-512.png',
  '/static/favicon.ico'
];

// 1. 설치 (Install) & 정적 파일 캐시
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      console.log('[ServiceWorker] 정적 자산 사전 캐싱 중...');
      return cache.addAll(PRECACHE_ASSETS).catch((err) => {
        console.warn('[ServiceWorker] 일부 파일 캐싱 실패(무시 가능):', err);
      });
    }).then(() => self.skipWaiting())
  );
});

// 2. 활성화 (Activate) & 구버전 캐시 정리
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((name) => {
          if (name !== CACHE_NAME) {
            console.log('[ServiceWorker] 구버전 캐시 삭제:', name);
            return caches.delete(name);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

// 3. 네트워크 요청 가로채기 (Fetch)
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // API 요청 및 POST 요청은 네트워크로 직접 전달
  if (event.request.method !== 'GET' || url.pathname.startsWith('/inspect') || url.pathname.startsWith('/suggest') || url.pathname.startsWith('/run') || url.pathname.startsWith('/query') || url.pathname.startsWith('/explain') || url.pathname.startsWith('/followup')) {
    return;
  }

  // 정적 리소스: Cache-First 또는 Stale-While-Revalidate
  event.respondWith(
    caches.match(event.request).then((cachedResponse) => {
      if (cachedResponse) {
        // 캐시가 있으면 반환하면서 백그라운드에서 최신화
        fetch(event.request).then((networkResponse) => {
          if (networkResponse && networkResponse.status === 200) {
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, networkResponse));
          }
        }).catch(() => {});
        return cachedResponse;
      }
      return fetch(event.request).then((networkResponse) => {
        if (!networkResponse || networkResponse.status !== 200 || networkResponse.type !== 'basic') {
          return networkResponse;
        }
        const responseToCache = networkResponse.clone();
        caches.open(CACHE_NAME).then((cache) => {
          cache.put(event.request, responseToCache);
        });
        return networkResponse;
      });
    })
  );
});
