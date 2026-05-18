<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { authedFetch } from '$lib/api';
  import { requireAuthRedirect } from '$lib/auth';
  import { createAsyncPoller, type AsyncPoller } from '$lib/polling';
  import {
    loadProtectedImageSrc,
    retainProtectedImageKeys,
    revokeProtectedImagePrefix
  } from '$lib/protectedImages';

  type ApiCarouselItem = {
    case_id: number;
    metadata: {
      child_name: string;
      animal_name: string;
      animal_type?: string;
      broken_bone: boolean;
      qr_content: string;
    };
    xray_url: string;
    original_url: string;
    approved_at: string;
  };

  type CarouselItem = ApiCarouselItem & {
    xray_src: string | null;
    original_src: string | null;
  };

  type CarouselResponse = {
    items: ApiCarouselItem[];
    max_items: number;
    autoplay_interval_seconds: number;
  };

  let items: CarouselItem[] = [];
  let index = 0;
  let intervalMs = 5000;

  let status = '';
  let autoplayHandle: ReturnType<typeof setInterval> | null = null;
  let refreshPoller: AsyncPoller | null = null;
  let carouselEtag: string | null = null;
  let visibleImageSignature = '';

  function imageKey(item: ApiCarouselItem, kind: 'xray' | 'original'): string {
    return `carousel:${item.case_id}:${item.approved_at}:${kind}`;
  }

  function sameCarouselItem(left: ApiCarouselItem, right: ApiCarouselItem): boolean {
    return left.case_id === right.case_id && left.approved_at === right.approved_at;
  }

  function existingImageSrc(item: ApiCarouselItem, kind: 'xray' | 'original'): string | null {
    const existing = items.find((candidate) => sameCarouselItem(candidate, item));
    return kind === 'xray' ? existing?.xray_src ?? null : existing?.original_src ?? null;
  }

  function next(): void {
    if (items.length === 0) {
      return;
    }
    index = (index + 1) % items.length;
  }

  function restartAutoplay(): void {
    if (autoplayHandle) {
      clearInterval(autoplayHandle);
      autoplayHandle = null;
    }

    autoplayHandle = setInterval(next, intervalMs);
  }

  function retainCurrentCarouselImages(nextItems: ApiCarouselItem[]): void {
    const activeKeys = new Set<string>();
    for (const item of nextItems) {
      activeKeys.add(imageKey(item, 'xray'));
      activeKeys.add(imageKey(item, 'original'));
    }
    retainProtectedImageKeys('carousel:', activeKeys);
  }

  async function ensureItemImages(itemIndex = index, signal?: AbortSignal): Promise<void> {
    const item = items[itemIndex];
    if (!item) {
      return;
    }

    const [originalSrc, xraySrc] = await Promise.all([
      loadProtectedImageSrc(item.original_url, imageKey(item, 'original'), signal),
      loadProtectedImageSrc(item.xray_url, imageKey(item, 'xray'), signal)
    ]);

    if (signal?.aborted) {
      return;
    }

    items = items.map((candidate) =>
      sameCarouselItem(candidate, item)
        ? {
            ...candidate,
            original_src: originalSrc ?? candidate.original_src,
            xray_src: xraySrc ?? candidate.xray_src
          }
        : candidate
    );
  }

  function prefetchNextImages(): void {
    if (items.length < 2) {
      return;
    }
    const nextIndex = (index + 1) % items.length;
    const item = items[nextIndex];
    void loadProtectedImageSrc(item.original_url, imageKey(item, 'original')).catch(() => undefined);
    void loadProtectedImageSrc(item.xray_url, imageKey(item, 'xray')).catch(() => undefined);
  }

  async function loadItems(signal?: AbortSignal): Promise<void> {
    const headers = new Headers();
    if (carouselEtag) {
      headers.set('If-None-Match', carouselEtag);
    }
    const response = await authedFetch('/api/carousel', { headers, signal });
    if (response.status === 304) {
      status = '';
      prefetchNextImages();
      return;
    }
    if (!response.ok) {
      status = 'Failed to load carousel.';
      throw new Error('Failed to load carousel');
    }

    const data = (await response.json()) as CarouselResponse;
    carouselEtag = response.headers.get('ETag') ?? carouselEtag;
    intervalMs = Math.max(1000, data.autoplay_interval_seconds * 1000);

    retainCurrentCarouselImages(data.items);
    items = data.items.map((item) => ({
      ...item,
      original_src: existingImageSrc(item, 'original'),
      xray_src: existingImageSrc(item, 'xray')
    }));
    status = '';

    if (index >= items.length) {
      index = Math.max(0, items.length - 1);
    }

    const currentItem = items[index];
    visibleImageSignature = currentItem ? `${currentItem.case_id}:${currentItem.approved_at}` : '';
    await ensureItemImages(index, signal);
    prefetchNextImages();
    restartAutoplay();
  }

  $: {
    const item = items[index];
    const signature = item ? `${item.case_id}:${item.approved_at}` : '';
    if (signature && signature !== visibleImageSignature) {
      visibleImageSignature = signature;
      void ensureItemImages(index)
        .then(() => prefetchNextImages())
        .catch(() => {
          status = 'Failed to load carousel image.';
        });
    }
  }

  onMount(async () => {
    const token = await requireAuthRedirect();
    if (!token) {
      return;
    }

    await loadItems();
    refreshPoller = createAsyncPoller((signal) => loadItems(signal), {
      intervalMs,
      maxIntervalMs: Math.max(intervalMs, 30000),
      pauseWhenHidden: true
    });
    refreshPoller.start(false);
  });

  onDestroy(() => {
    if (autoplayHandle) {
      clearInterval(autoplayHandle);
    }
    refreshPoller?.stop();
    refreshPoller = null;
    revokeProtectedImagePrefix('carousel:');
  });
</script>

<div class="card showcase-card">
  {#if items.length === 0}
    <p>No approved images yet.</p>
  {:else}
    <div class="image-row">
      <article class="image-panel">
        {#if items[index].original_src}
          <img class="preview" src={items[index].original_src} alt="Carousel original" style="width:100%;" />
        {:else}
          <div class="preview unavailable">Original image unavailable</div>
        {/if}
      </article>

      <article class="image-panel">
        {#if items[index].xray_src}
          <img class="preview" src={items[index].xray_src} alt="Carousel X-Ray" style="width:100%;" />
        {:else}
          <div class="preview unavailable">X-Ray unavailable</div>
        {/if}
      </article>
    </div>
  {/if}

  {#if status}
    <p style="color:#b23a48;">{status}</p>
  {/if}
</div>

<style>
  .showcase-card {
    width: 100%;
    margin: 0;
  }

  .image-row {
    display: grid;
    gap: 1rem;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    align-items: start;
  }

  .unavailable {
    display: grid;
    place-items: center;
    min-height: 280px;
    color: #6d6d6d;
    background: #f6f6f6;
    border: 1px solid var(--border);
    border-radius: 10px;
  }

  @media (max-width: 900px) {
    .image-row {
      grid-template-columns: 1fr;
    }
  }
</style>
