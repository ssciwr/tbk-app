<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import CaseNavigator from '$lib/components/CaseNavigator.svelte';
  import { authedFetch, authedFetchUrl } from '$lib/api';
  import { formatCaseNavigatorLabel, hasText, isQrOnlyCase } from '$lib/caseDisplay';
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
  let visibleCaseIds: number[] = [];
  let selectedItem: CarouselItem | undefined;
  let selectedCaseId: number | null = null;
  let showOriginal = false;
  let maxItems = 10;
  let refreshMs = 5000;

  let status = '';
  let refreshHandle: ReturnType<typeof setInterval> | null = null;
  let activeObjectUrls: string[] = [];

  $: selectedItem = items.find((item) => item.case_id === selectedCaseId);

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

    if (!items.some((item) => item.case_id === selectedCaseId)) {
      selectedCaseId = items[0]?.case_id ?? null;
    }

    restartRefresh();
  }

  function next(): void {
    if (visibleCaseIds.length === 0) {
      return;
    }
    const currentIndex = visibleCaseIds.indexOf(selectedCaseId ?? -1);
    selectedCaseId = visibleCaseIds[(currentIndex + 1) % visibleCaseIds.length];
  }

  function prev(): void {
    if (visibleCaseIds.length === 0) {
      return;
    }
    const currentIndex = visibleCaseIds.indexOf(selectedCaseId ?? -1);
    const previousIndex = currentIndex <= 0 ? visibleCaseIds.length - 1 : currentIndex - 1;
    selectedCaseId = visibleCaseIds[previousIndex];
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

<div class="results-layout">
  <CaseNavigator
    {items}
    bind:selectedCaseId
    bind:visibleCaseIds
    {maxItems}
    itemLabel="results"
    ariaLabel="Approved results"
    emptyMessage="No approved images yet."
  />

  <section class="card result-detail" aria-live="polite">
    {#if selectedItem}
      <div class="detail-toolbar">
        <div class="result-navigation">
          <button on:click={prev} disabled={visibleCaseIds.length < 2}>Prev</button>
          <button on:click={next} disabled={visibleCaseIds.length < 2}>Next</button>
        </div>

        <label class="original-toggle">
          <input type="checkbox" bind:checked={showOriginal} />
          Also show original image
        </label>
      </div>

      <h2>{formatCaseNavigatorLabel(selectedItem.metadata)}</h2>
      <p class="approval-time">Approved at {new Date(selectedItem.approved_at).toLocaleString()}</p>

      <div class="meta-grid">
        <p><strong>Case:</strong> #{selectedItem.case_id}</p>
        {#if hasText(selectedItem.metadata.child_name)}
          <p><strong>Child:</strong> {selectedItem.metadata.child_name}</p>
        {/if}
        {#if hasText(selectedItem.metadata.animal_name)}
          <p><strong>Animal:</strong> {selectedItem.metadata.animal_name}</p>
        {/if}
        {#if isQrOnlyCase(selectedItem.metadata)}
          <p><strong>Mode:</strong> QR-only fast-track</p>
        {/if}
        <p><strong>QR:</strong> {selectedItem.metadata.qr_content}</p>
      </div>

      {#if showOriginal}
        <div class="image-row">
          <article class="image-panel">
            <h3>Original</h3>
            {#if selectedItem.original_src}
              <img class="preview" src={selectedItem.original_src} alt="Case original" />
            {:else}
              <div class="preview unavailable">Original image unavailable</div>
            {/if}
          </article>

          <article class="image-panel">
            <h3>X-Ray</h3>
            {#if selectedItem.xray_src}
              <img class="preview" src={selectedItem.xray_src} alt="Case X-Ray" />
            {:else}
              <div class="preview unavailable">X-Ray unavailable</div>
            {/if}
          </article>
        </div>
      {:else if selectedItem.xray_src}
        <img class="preview result-image" src={selectedItem.xray_src} alt="Case X-Ray" />
      {:else}
        <div class="preview unavailable result-image">X-Ray unavailable</div>
      {/if}
    {:else if items.length > 0}
      <p>Select a result from the list.</p>
    {:else}
      <p>No approved image selected.</p>
    {/if}

    {#if status}
      <p class="error-message">{status}</p>
    {/if}
  </section>
</div>

<style>
  .results-layout {
    display: grid;
    grid-template-columns: minmax(220px, 280px) minmax(0, 1fr);
    gap: 1rem;
    align-items: start;
  }

  .detail-toolbar {
    display: flex;
    justify-content: space-between;
    gap: 1rem;
    align-items: center;
    flex-wrap: wrap;
  }

  .result-navigation {
    display: flex;
    gap: 0.6rem;
  }

  .original-toggle {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin: 0;
  }

  .original-toggle input {
    width: auto;
  }

  .result-detail h2 {
    margin: 1rem 0 0.15rem;
  }

  .approval-time {
    margin: 0 0 0.8rem;
    color: #4f5a60;
  }

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

  .image-panel .preview {
    width: 100%;
  }

  .result-image {
    width: min(100%, 900px);
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

  .error-message {
    color: #b23a48;
  }

  @media (max-width: 760px) {
    .results-layout {
      grid-template-columns: 1fr;
    }

  }
</style>
