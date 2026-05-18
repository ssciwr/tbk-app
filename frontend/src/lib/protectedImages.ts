import { authedFetchUrl } from '$lib/api';

type ProtectedImageEntry = {
  src: string;
  url: string;
  etag: string | null;
};

const imageCache = new Map<string, ProtectedImageEntry>();
const inFlightLoads = new Map<string, Promise<string | null>>();

export async function loadProtectedImageSrc(
  url: string,
  cacheKey: string,
  signal?: AbortSignal
): Promise<string | null> {
  if (!url) {
    return null;
  }
  if (url.startsWith('data:') || url.startsWith('blob:')) {
    return url;
  }

  const existing = imageCache.get(cacheKey);
  if (existing?.url === url) {
    return existing.src;
  }

  const inFlightKey = `${cacheKey}\n${url}`;
  const inFlight = inFlightLoads.get(inFlightKey);
  if (inFlight) {
    return inFlight;
  }

  const load = (async () => {
    const headers = new Headers();
    if (existing?.etag) {
      headers.set('If-None-Match', existing.etag);
    }

    const response = await authedFetchUrl(url, { headers, signal });
    if (response.status === 304 && existing) {
      return existing.src;
    }
    if (!response.ok) {
      return existing?.src ?? null;
    }

    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    const previous = imageCache.get(cacheKey);
    if (previous) {
      URL.revokeObjectURL(previous.src);
    }

    imageCache.set(cacheKey, {
      src: objectUrl,
      url,
      etag: response.headers.get('ETag')
    });
    return objectUrl;
  })();

  inFlightLoads.set(inFlightKey, load);
  try {
    return await load;
  } finally {
    inFlightLoads.delete(inFlightKey);
  }
}

export function retainProtectedImageKeys(prefix: string, activeKeys: Set<string>): void {
  for (const [key, entry] of imageCache) {
    if (key.startsWith(prefix) && !activeKeys.has(key)) {
      URL.revokeObjectURL(entry.src);
      imageCache.delete(key);
    }
  }
}

export function revokeProtectedImagePrefix(prefix: string): void {
  for (const [key, entry] of imageCache) {
    if (key.startsWith(prefix)) {
      URL.revokeObjectURL(entry.src);
      imageCache.delete(key);
    }
  }
}
