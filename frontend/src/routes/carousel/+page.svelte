<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { authedFetch, authedFetchUrl } from '$lib/api';
  import { requireAuthRedirect } from '$lib/auth';

  type ApiCarouselItem = {
    xray_url: string;
    original_url: string;
    approved_at: string;
  };

  type CarouselItem = ApiCarouselItem & {
    xray_src: string | null;
    original_src: string | null;
  };

  let items: CarouselItem[] = [];
  let index = 0;
  let showOriginal = false;
  let autoplay = false;
  let intervalMs = 5000;

  let status = '';
  let autoplayHandle: ReturnType<typeof setInterval> | null = null;
  let refreshHandle: ReturnType<typeof setInterval> | null = null;
  let activeObjectUrls: string[] = [];

  function revokeObjectUrls(urls: string[]): void {
    for (const url of urls) {
      URL.revokeObjectURL(url);
    }
  }

  async function toProtectedImageSrc(url: string, objectUrls: string[]): Promise<string | null> {
    if (!url) {
      return null;
    }
    if (url.startsWith('data:') || url.startsWith('blob:')) {
      return url;
    }
    const response = await authedFetchUrl(url);
    if (!response.ok) {
      return null;
    }
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    objectUrls.push(objectUrl);
    return objectUrl;
  }

  async function loadItems(): Promise<void> {
    const response = await authedFetch('/api/carousel');
    if (!response.ok) {
      status = 'Failed to load carousel.';
      return;
    }

    const data = (await response.json()) as { items: ApiCarouselItem[] };
    const nextObjectUrls: string[] = [];
    const hydratedItems: CarouselItem[] = await Promise.all(
      data.items.map(async (item) => ({
        ...item,
        xray_src: await toProtectedImageSrc(item.xray_url, nextObjectUrls),
        original_src: await toProtectedImageSrc(item.original_url, nextObjectUrls)
      }))
    );

    const previousObjectUrls = activeObjectUrls;
    activeObjectUrls = nextObjectUrls;
    revokeObjectUrls(previousObjectUrls);
    items = hydratedItems;
    if (index >= items.length) {
      index = Math.max(0, items.length - 1);
    }
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

  function restartAutoplay(): void {
    if (autoplayHandle) {
      clearInterval(autoplayHandle);
      autoplayHandle = null;
    }
    if (autoplay) {
      autoplayHandle = setInterval(next, intervalMs);
    }
  }

  async function openFullscreen(): Promise<void> {
    const root = document.documentElement;
    if (root.requestFullscreen) {
      await root.requestFullscreen();
    }
  }

  $: restartAutoplay();

  onMount(async () => {
    const token = await requireAuthRedirect();
    if (!token) {
      return;
    }

    await loadItems();
    refreshHandle = setInterval(loadItems, 5000);
  });

  onDestroy(() => {
    if (autoplayHandle) {
      clearInterval(autoplayHandle);
    }
    if (refreshHandle) {
      clearInterval(refreshHandle);
    }
    revokeObjectUrls(activeObjectUrls);
    activeObjectUrls = [];
  });
</script>

<div class="card">
  <h1>Carousel</h1>
  <p>Cycle through accepted X-Rays with manual controls or autoplay.</p>

  <div style="display:flex; gap:0.6rem; flex-wrap:wrap; margin-bottom:0.8rem;">
    <button on:click={prev} disabled={items.length === 0}>Prev</button>
    <button on:click={next} disabled={items.length === 0}>Next</button>
    <button class="secondary" on:click={() => (autoplay = !autoplay)}>
      {autoplay ? 'Stop Autoplay' : 'Start Autoplay'}
    </button>
    <button class="secondary" on:click={openFullscreen}>Fullscreen</button>
  </div>

  <label>
    Autoplay interval (ms)
    <input type="number" min="1000" step="500" bind:value={intervalMs} />
  </label>

  <label style="display:flex; align-items:center; gap:0.5rem; margin-top:0.6rem;">
    <input type="checkbox" bind:checked={showOriginal} style="width:auto;" />
    Show original image instead of X-Ray
  </label>

  {#if items.length === 0}
    <p>No approved images yet.</p>
  {:else}
    <p>Showing {index + 1} / {items.length} | Approved at {new Date(items[index].approved_at).toLocaleString()}</p>
    {#if showOriginal ? items[index].original_src : items[index].xray_src}
      <img
        class="preview"
        src={showOriginal ? items[index].original_src : items[index].xray_src}
        alt="Carousel image"
        style="width:min(100%, 900px);"
      />
    {:else}
      <div
        class="preview"
        style="display:grid; place-items:center; min-height:240px; color:#6d6d6d; background:#f6f6f6; width:min(100%, 900px);"
      >
        Image unavailable
      </div>
    {/if}
  {/if}

  {#if status}
    <p style="color:#b23a48;">{status}</p>
  {/if}
</div>
