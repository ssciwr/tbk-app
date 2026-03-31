<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { authedFetch, authedFetchUrl } from '$lib/api';
  import { requireAuthRedirect } from '$lib/auth';

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
    try {
      const response = await authedFetchUrl(url);
      if (!response.ok) {
        return null;
      }
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      objectUrls.push(objectUrl);
      return objectUrl;
    } catch {
      return null;
    }
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
    intervalMs = Math.max(1000, data.autoplay_interval_seconds * 1000);

    const nextObjectUrls: string[] = [];
    const hydratedItems: CarouselItem[] = await Promise.all(
      data.items.map(async (item) => ({
        ...item,
        original_src: await toProtectedImageSrc(item.original_url, nextObjectUrls),
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
