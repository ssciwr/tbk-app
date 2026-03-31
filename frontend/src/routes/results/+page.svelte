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
  let showOriginal = false;
  let maxItems = 10;
  let refreshMs = 5000;

  let status = '';
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

  function restartRefresh(): void {
    if (refreshHandle) {
      clearInterval(refreshHandle);
      refreshHandle = null;
    }
    refreshHandle = setInterval(loadItems, refreshMs);
  }

  async function loadItems(): Promise<void> {
    const response = await authedFetch('/api/carousel');
    if (!response.ok) {
      status = 'Failed to load recent results.';
      return;
    }

    const data = (await response.json()) as CarouselResponse;
    maxItems = data.max_items;
    refreshMs = Math.max(1000, data.autoplay_interval_seconds * 1000);

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
    status = '';

    if (index >= items.length) {
      index = Math.max(0, items.length - 1);
    }

    restartRefresh();
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

  onMount(async () => {
    const token = await requireAuthRedirect();
    if (!token) {
      return;
    }

    await loadItems();
  });

  onDestroy(() => {
    if (refreshHandle) {
      clearInterval(refreshHandle);
    }
    revokeObjectUrls(activeObjectUrls);
    activeObjectUrls = [];
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
      <p><strong>Child:</strong> {items[index].metadata.child_name}</p>
      <p><strong>Animal:</strong> {items[index].metadata.animal_name}</p>
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
