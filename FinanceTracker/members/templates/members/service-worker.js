const CACHE_NAME = 'sable-static-v2';
const CACHE_PREFIX = 'sable-static-';

self.addEventListener('install', () => {
    self.skipWaiting();
});

self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys()
            .then(keys => Promise.all(
                keys
                    .filter(key => key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME)
                    .map(key => caches.delete(key))
            ))
            .then(() => self.clients.claim())
    );
});

self.addEventListener('fetch', event => {
    const request = event.request;
    const url = new URL(request.url);

    if (
        request.method !== 'GET'
        || url.origin !== self.location.origin
        || !url.pathname.startsWith('/static/')
    ) {
        return;
    }

    event.respondWith(
        caches.open(CACHE_NAME).then(async cache => {
            const cached = await cache.match(request);
            if (cached) return cached;

            const response = await fetch(request);
            if (response.ok && response.type === 'basic') {
                try {
                    await cache.put(request, response.clone());
                } catch (error) {
                    console.error('Sable static asset could not be cached:', error);
                }
            }
            return response;
        })
    );
});
