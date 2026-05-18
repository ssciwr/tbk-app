<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { authedFetch } from '$lib/api';
  import { hasText, isQrOnlyCase } from '$lib/caseDisplay';
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
  let showOriginal = false;
  let maxItems = 10;
  let refreshMs = 5000;

  let status = '';
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

  function retainCurrentCarouselImages(nextItems: ApiCarouselItem[]): void {
    const activeKeys = new Set<string>();
    for (const item of nextItems) {
      activeKeys.add(imageKey(item, 'xray'));
      activeKeys.add(imageKey(item, 'original'));
    }
    retainProtectedImageKeys('carousel:', activeKeys);
  }

  async function ensureItemImages(
    itemIndex = index,
    includeOriginal = showOriginal,
    signal?: AbortSignal
  ): Promise<void> {
    const item = items[itemIndex];
    if (!item) {
      return;
    }

    const xraySrc = await loadProtectedImageSrc(item.xray_url, imageKey(item, 'xray'), signal);
    const originalSrc = includeOriginal
      ? await loadProtectedImageSrc(item.original_url, imageKey(item, 'original'), signal)
      : item.original_src;

    if (signal?.aborted) {
      return;
    }

    items = items.map((candidate) =>
      sameCarouselItem(candidate, item)
        ? {
            ...candidate,
            xray_src: xraySrc ?? candidate.xray_src,
            original_src: includeOriginal ? originalSrc ?? candidate.original_src : candidate.original_src
          }
        : candidate
    );
  }

  function prefetchNextImage(): void {
    if (items.length < 2) {
      return;
    }
    const nextIndex = (index + 1) % items.length;
    const item = items[nextIndex];
    void loadProtectedImageSrc(item.xray_url, imageKey(item, 'xray')).catch(() => undefined);
    if (showOriginal) {
      void loadProtectedImageSrc(item.original_url, imageKey(item, 'original')).catch(() => undefined);
    }
  }

  async function loadItems(signal?: AbortSignal): Promise<void> {
    const headers = new Headers();
    if (carouselEtag) {
      headers.set('If-None-Match', carouselEtag);
    }
    const response = await authedFetch('/api/carousel', { headers, signal });
    if (response.status === 304) {
      status = '';
      prefetchNextImage();
      return;
    }
    if (!response.ok) {
      status = 'Failed to load recent results.';
      throw new Error('Failed to load recent results');
    }

    const data = (await response.json()) as CarouselResponse;
    carouselEtag = response.headers.get('ETag') ?? carouselEtag;
    maxItems = data.max_items;
    refreshMs = Math.max(1000, data.autoplay_interval_seconds * 1000);

    retainCurrentCarouselImages(data.items);
    items = data.items.map((item) => ({
      ...item,
      xray_src: existingImageSrc(item, 'xray'),
      original_src: existingImageSrc(item, 'original')
    }));
    status = '';

    if (index >= items.length) {
      index = Math.max(0, items.length - 1);
    }

    const currentItem = items[index];
    visibleImageSignature = currentItem
      ? `${currentItem.case_id}:${currentItem.approved_at}:${showOriginal ? 'with-original' : 'xray'}`
      : '';
    await ensureItemImages(index, showOriginal, signal);
    prefetchNextImage();
  }

  function next(): void {
    if (items.length === 0) {
      return;
    }
    index = (index + 1) % items.length;
  }

  function prev(): void {
    if (items.length === 0) {
      return;
    }
    index = (index - 1 + items.length) % items.length;
  }

  $: {
    const item = items[index];
    const signature = item
      ? `${item.case_id}:${item.approved_at}:${showOriginal ? 'with-original' : 'xray'}`
      : '';
    if (signature && signature !== visibleImageSignature) {
      visibleImageSignature = signature;
      void ensureItemImages(index, showOriginal)
        .then(() => prefetchNextImage())
        .catch(() => {
          status = 'Failed to load recent result image.';
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
      intervalMs: refreshMs,
      maxIntervalMs: Math.max(refreshMs, 30000),
      pauseWhenHidden: true
    });
    refreshPoller.start(false);
  });

  onDestroy(() => {
    refreshPoller?.stop();
    refreshPoller = null;
    revokeProtectedImagePrefix('carousel:');
  });
</script>

<div class="card">
  <div style="display:flex; gap:0.6rem; flex-wrap:wrap; margin-bottom:0.8rem;">
    <button on:click={prev} disabled={items.length === 0}>Prev</button>
    <button on:click={next} disabled={items.length === 0}>Next</button>
  </div>

  <label style="display:flex; align-items:center; gap:0.5rem; margin-top:0.6rem;">
    <input type="checkbox" bind:checked={showOriginal} style="width:auto;" />
    Also show original image
  </label>

  {#if items.length === 0}
    <p>No approved images yet.</p>
  {:else}
    <p>
      Showing {index + 1} / {items.length}
      | Approved at {new Date(items[index].approved_at).toLocaleString()}
    </p>

    <div class="meta-grid">
      <p><strong>Case:</strong> #{items[index].case_id}</p>
      {#if hasText(items[index].metadata.child_name)}
        <p><strong>Child:</strong> {items[index].metadata.child_name}</p>
      {/if}
      {#if hasText(items[index].metadata.animal_name)}
        <p><strong>Animal:</strong> {items[index].metadata.animal_name}</p>
      {/if}
      {#if isQrOnlyCase(items[index].metadata)}
        <p><strong>Mode:</strong> QR-only fast-track</p>
      {/if}
      <p><strong>QR:</strong> {items[index].metadata.qr_content}</p>
    </div>

    {#if showOriginal}
      <div class="image-row">
        <article class="image-panel">
          <h3>Original</h3>
          {#if items[index].original_src}
            <img
              class="preview"
              src={items[index].original_src}
              alt="Case original"
              style="width:100%;"
            />
          {:else}
            <div class="preview unavailable">Original image unavailable</div>
          {/if}
        </article>

        <article class="image-panel">
          <h3>X-Ray</h3>
          {#if items[index].xray_src}
            <img
              class="preview"
              src={items[index].xray_src}
              alt="Case X-Ray"
              style="width:100%;"
            />
          {:else}
            <div class="preview unavailable">X-Ray unavailable</div>
          {/if}
        </article>
      </div>
    {:else if items[index].xray_src}
      <img
        class="preview"
        src={items[index].xray_src}
        alt="Case X-Ray"
        style="width:min(100%, 900px);"
      />
    {:else}
      <div class="preview unavailable" style="width:min(100%, 900px);">X-Ray unavailable</div>
    {/if}
  {/if}

  {#if status}
    <p style="color:#b23a48;">{status}</p>
  {/if}
</div>

<style>
  .meta-grid {
    display: grid;
    gap: 0.25rem;
    margin: 0.6rem 0 0.9rem;
  }

  .meta-grid p {
    margin: 0;
  }

  .image-row {
    display: grid;
    gap: 0.8rem;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    max-width: 1100px;
  }

  .image-panel h3 {
    margin: 0 0 0.4rem;
  }

  .unavailable {
    display: grid;
    place-items: center;
    min-height: 240px;
    color: #6d6d6d;
    background: #f6f6f6;
    border: 1px solid var(--border);
    border-radius: 10px;
  }
</style>
