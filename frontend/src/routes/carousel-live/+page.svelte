<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { authedFetch, authedFetchUrl } from '$lib/api';
  import { requireAuthRedirect } from '$lib/auth';

  type ApiCarouselItem = {
    case_id: number;
    metadata: {
      child_name: string;
      animal_name: string;
      broken_bone: boolean;
      qr_content: string;
    };
    xray_url: string;
    original_url: string;
    approved_at: string;
  };

  type CarouselItem = ApiCarouselItem & {
    xray_src: string | null;
  };

  type CarouselResponse = {
    items: ApiCarouselItem[];
    max_items: number;
    autoplay_interval_seconds: number;
  };

  let items: CarouselItem[] = [];
  let index = 0;
  let intervalMs = 5000;
  let maxItems = 10;

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

  function next(): void {
    if (items.length === 0) {
      return;
    }
    index = (index + 1) % items.length;
  }

  function restartTimers(): void {
    if (autoplayHandle) {
      clearInterval(autoplayHandle);
      autoplayHandle = null;
    }
    if (refreshHandle) {
      clearInterval(refreshHandle);
      refreshHandle = null;
    }

    autoplayHandle = setInterval(next, intervalMs);
    refreshHandle = setInterval(loadItems, intervalMs);
  }

  async function loadItems(): Promise<void> {
    const response = await authedFetch('/api/carousel');
    if (!response.ok) {
      status = 'Failed to load carousel.';
      return;
    }

    const data = (await response.json()) as CarouselResponse;
    maxItems = data.max_items;
    intervalMs = Math.max(1000, data.autoplay_interval_seconds * 1000);

    const nextObjectUrls: string[] = [];
    const hydratedItems: CarouselItem[] = await Promise.all(
      data.items.map(async (item) => ({
        ...item,
        xray_src: await toProtectedImageSrc(item.xray_url, nextObjectUrls)
      }))
    );

    const previousObjectUrls = activeObjectUrls;
    activeObjectUrls = nextObjectUrls;
    revokeObjectUrls(previousObjectUrls);
    items = hydratedItems;
    status = '';

    if (index >= items.length) {
      index = Math.max(0, items.length - 1);
    }

    restartTimers();
  }

  onMount(async () => {
    const token = await requireAuthRedirect();
    if (!token) {
      return;
    }

    await loadItems();
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

<div class="card showcase-card">
  <h1>Carousel</h1>
  <p>Autoplaying the most recent {maxItems} approved X-Rays.</p>

  {#if items.length === 0}
    <p>No approved images yet.</p>
  {:else}
    <p>
      Showing {index + 1} / {items.length}
      | Approved at {new Date(items[index].approved_at).toLocaleString()}
    </p>

    <div class="meta-grid">
      <p><strong>Case:</strong> #{items[index].case_id}</p>
      <p><strong>Child:</strong> {items[index].metadata.child_name}</p>
      <p><strong>Animal:</strong> {items[index].metadata.animal_name}</p>
      <p><strong>QR:</strong> {items[index].metadata.qr_content}</p>
    </div>

    {#if items[index].xray_src}
      <img class="preview" src={items[index].xray_src} alt="Carousel X-Ray" style="width:min(100%, 1100px);" />
    {:else}
      <div
        class="preview"
        style="display:grid; place-items:center; min-height:300px; color:#6d6d6d; background:#f6f6f6; width:min(100%, 1100px);"
      >
        Image unavailable
      </div>
    {/if}
  {/if}

  {#if status}
    <p style="color:#b23a48;">{status}</p>
  {/if}
</div>

<style>
  .showcase-card {
    max-width: 1200px;
    margin: 1rem auto;
  }

  .meta-grid {
    display: grid;
    gap: 0.25rem;
    margin: 0.6rem 0 0.9rem;
  }

  .meta-grid p {
    margin: 0;
  }
</style>
