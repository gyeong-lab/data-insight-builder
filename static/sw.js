const CACHE_NAME = 'data-insight-v4';
const PRECACHE_ASSETS = [
  '/',
  '/manifest.json',
  '/static/icon-192.png',
  '/static/icon-512.png',
  '/static/favicon.ico'
];

// 1. 설치 (Install) & 정적 파일 캐시
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      console.log('[ServiceWorker] 핵심 자산 캐싱 중...');
      return cache.addAll(PRECACHE_ASSETS).catch((err) => {
        console.warn('[ServiceWorker] 일부 파일 캐싱 실패:', err);
      });
    }).then(() => self.skipWaiting())
  );
});

// 2. 활성화 (Activate) & 구버전 캐시 즉시 완전 삭제
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((name) => {
          if (name !== CACHE_NAME) {
            console.log('[ServiceWorker] 구버전 캐시 즉시 제거:', name);
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

  // 모든 API 요청 및 동적 헬스체크는 캐시를 거치지 않고 네트워크로 직접 전달
  if (
    event.request.method !== 'GET' ||
    url.pathname === '/health' ||
    url.pathname.startsWith('/health') ||
    url.pathname.startsWith('/api') ||
    url.pathname.startsWith('/inspect') ||
    url.pathname.startsWith('/suggest') ||
    url.pathname.startsWith('/run') ||
    url.pathname.startsWith('/query') ||
    url.pathname.startsWith('/explain') ||
    url.pathname.startsWith('/followup')
  ) {
    return;
  }

  // JS/CSS 및 메인 페이지는 Network-First (온라인 우선 최신 반영, 오프라인 시 캐시 활용)
  if (url.pathname.endsWith('.js') || url.pathname.endsWith('.css') || url.pathname === '/') {
    event.respondWith(
      fetch(event.request)
        .then((networkResponse) => {
          if (networkResponse && networkResponse.status === 200) {
            const responseClone = networkResponse.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, responseClone));
          }
          return networkResponse;
        })
        .catch(() => caches.match(event.request))
    );
    return;
  }

  // 기타 정적 에셋(이미지, 아이콘): Cache-First
  event.respondWith(
    caches.match(event.request).then((cachedResponse) => {
      if (cachedResponse) {
        return cachedResponse;
      }
      return fetch(event.request).then((networkResponse) => {
        if (!networkResponse || networkResponse.status !== 200 || networkResponse.type !== 'basic') {
          return networkResponse;
        }
        const responseClone = networkResponse.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, responseClone));
        return networkResponse;
      });
    })
  );
});
