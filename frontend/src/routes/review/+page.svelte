<script lang="ts">
  import { goto } from '$app/navigation';
  import { onDestroy, onMount } from 'svelte';
  import { authedFetch, authedFetchUrl } from '$lib/api';
  import { requireAuthRedirect } from '$lib/auth';

  type ApiPendingCase = {
    case_id: number;
    status: 'queued' | 'collecting_results' | 'retried' | 'awaiting_review';
    received_results: number;
    ready_for_review: boolean;
    metadata: {
      child_name: string;
      animal_name: string;
      broken_bone: boolean;
    };
    original_url: string;
    result_urls: string[];
    results_per_image: number;
  };

  type PendingCase = Omit<ApiPendingCase, 'original_url' | 'result_urls'> & {
    original_url: string | null;
    result_urls: Array<string | null>;
  };

  let cases: PendingCase[] = [];
  let loading = true;
  let error = '';
  let actionMessage = '';
  let pollHandle: ReturnType<typeof setInterval> | null = null;
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

  async function hydrateCaseImages(
    pending: ApiPendingCase,
    objectUrls: string[]
  ): Promise<PendingCase> {
    const [originalSrc, resultSrcs] = await Promise.all([
      toProtectedImageSrc(pending.original_url, objectUrls),
      Promise.all(pending.result_urls.map((url) => toProtectedImageSrc(url, objectUrls)))
    ]);

    return {
      ...pending,
      original_url: originalSrc,
      result_urls: resultSrcs
    };
  }

  function resultSlots(pending: PendingCase): Array<string | null> {
    return Array.from({ length: pending.results_per_image }, (_, index) => pending.result_urls[index] ?? null);
  }

  async function loadPending(): Promise<void> {
    const response = await authedFetch('/api/review/pending');
    if (!response.ok) {
      error = 'Failed to load pending review cases.';
      loading = false;
      return;
    }

    const data = (await response.json()) as { cases: ApiPendingCase[] };
    const nextObjectUrls: string[] = [];
    const hydratedCases = await Promise.all(
      data.cases.map((pending) => hydrateCaseImages(pending, nextObjectUrls))
    );
    const previousObjectUrls = activeObjectUrls;
    activeObjectUrls = nextObjectUrls;
    revokeObjectUrls(previousObjectUrls);
    cases = hydratedCases;
    loading = false;
  }

  async function decide(caseId: number, action: 'confirm' | 'retry' | 'cancel', choiceIndex: number | null): Promise<void> {
    actionMessage = '';
    const response = await authedFetch(`/api/review/${caseId}/decision`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, choice_index: choiceIndex })
    });

    if (!response.ok) {
      actionMessage = `Failed to ${action} case ${caseId}.`;
      return;
    }

    let nextStage: 'fracture' | 'results' | undefined;
    try {
      const payload = (await response.json()) as { next_stage?: string };
      if (payload.next_stage === 'fracture' || payload.next_stage === 'results') {
        nextStage = payload.next_stage;
      }
    } catch {
      // Keep default transition when no payload is available.
    }

    if (action === 'confirm') {
      await goto(nextStage === 'results' ? '/results' : '/fracture');
      return;
    }

    actionMessage = `Case ${caseId}: ${action} applied.`;
    await loadPending();
  }

  onMount(async () => {
    const token = await requireAuthRedirect();
    if (!token) {
      return;
    }

    await loadPending();
    pollHandle = setInterval(loadPending, 2000);
  });

  onDestroy(() => {
    if (pollHandle) {
      clearInterval(pollHandle);
      pollHandle = null;
    }
    revokeObjectUrls(activeObjectUrls);
    activeObjectUrls = [];
  });
</script>

<div class="card">
  <h1>Review Results</h1>
  <p>Accept one generated X-Ray, reject all and retry, or cancel the case.</p>

  {#if actionMessage}
    <p>{actionMessage}</p>
  {/if}
  {#if error}
    <p style="color:#b23a48;">{error}</p>
  {/if}

  {#if loading}
    <p>Loading pending cases...</p>
  {:else if cases.length === 0}
    <p>No cases awaiting review.</p>
  {:else}
    <div class="grid">
      {#each cases as pending}
        <article class="card result-case">
          <div class="case-layout">
            <div class="case-top-row">
              <section class="meta-panel">
                <h2>Case #{pending.case_id}</h2>
                <p class="meta-line">Child: {pending.metadata.child_name}</p>
                <p class="meta-line">Animal: {pending.metadata.animal_name}</p>
                {#if !pending.ready_for_review}
                  <p class="generation-note">
                    Image currently generating ({pending.received_results}/{pending.results_per_image})
                  </p>
                {/if}
                <div class="meta-actions">
                  <button
                    class="secondary"
                    on:click={() => decide(pending.case_id, 'retry', null)}
                    disabled={!pending.ready_for_review}
                  >
                    Reject All
                  </button>
                  <button class="warn" on:click={() => decide(pending.case_id, 'cancel', null)}>Cancel</button>
                </div>
              </section>

              <section class="original-panel">
                <h3>Original</h3>
                {#if pending.original_url}
                  <img
                    class="preview original-image"
                    src={pending.original_url}
                    alt={`Original for case ${pending.case_id}`}
                  />
                {:else}
                  <div class="preview-frame">Original image unavailable</div>
                {/if}
              </section>
            </div>

            <section class="candidates-panel">
              <h3>Candidates</h3>
              <div class="candidate-grid">
                {#each resultSlots(pending) as resultUrl, index}
                  <article class="candidate-card">
                    {#if resultUrl}
                      <img class="preview candidate-image" src={resultUrl} alt={`Result ${index} for case ${pending.case_id}`} />
                      <button class="ok" on:click={() => decide(pending.case_id, 'confirm', index)}>Accept</button>
                    {:else}
                      <div class="preview-frame">Image currently generating</div>
                    {/if}
                  </article>
                {/each}
              </div>
            </section>
          </div>
        </article>
      {/each}
    </div>
  {/if}
</div>

<style>
  .result-case {
    background: #fff;
  }

  .case-layout {
    display: grid;
    gap: 1rem;
  }

  .case-top-row {
    display: grid;
    grid-template-columns: minmax(200px, 260px) minmax(250px, 320px);
    justify-content: center;
    align-items: start;
    column-gap: 2.4rem;
    row-gap: 1rem;
  }

  .meta-panel {
    display: grid;
    gap: 0.5rem;
    align-content: start;
  }

  .meta-panel h2 {
    margin: 0;
  }

  .meta-line {
    margin: 0;
    font-size: 1.8rem;
    line-height: 1.05;
    font-weight: 700;
  }

  .generation-note {
    margin: 0.2rem 0 0;
    color: #5e646c;
    font-size: 0.95rem;
  }

  .meta-actions {
    margin-top: 0.35rem;
    display: grid;
    gap: 0.45rem;
    max-width: 220px;
  }

  .meta-actions button {
    width: 100%;
  }

  .original-panel {
    display: grid;
    gap: 0.5rem;
    justify-items: center;
  }

  .original-panel h3,
  .candidates-panel h3 {
    margin: 0;
  }

  .original-image {
    width: min(100%, 290px);
    aspect-ratio: 1 / 1;
    object-fit: cover;
  }

  .preview-frame {
    width: min(100%, 290px);
    aspect-ratio: 1 / 1;
    display: grid;
    place-items: center;
    padding: 0.9rem;
    border: 1px solid var(--border);
    border-radius: 10px;
    color: #6d6d6d;
    background: #f6f6f6;
    text-align: center;
  }

  .candidates-panel {
    border-top: 1px solid var(--border);
    padding-top: 0.9rem;
    display: grid;
    gap: 0.6rem;
  }

  .candidate-grid {
    display: grid;
    gap: 0.9rem;
    grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  }

  .candidate-card {
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 0.7rem;
    background: #fff;
    display: grid;
    gap: 0.55rem;
    align-content: start;
  }

  .candidate-image {
    width: 100%;
    aspect-ratio: 1 / 1;
    object-fit: cover;
  }

  .candidate-card button {
    width: 100%;
  }

  .candidate-card .preview-frame {
    width: 100%;
  }

  @media (max-width: 900px) {
    .case-top-row {
      grid-template-columns: 1fr;
      justify-content: stretch;
      column-gap: 0;
    }

    .meta-actions {
      max-width: none;
    }

    .original-panel {
      justify-items: stretch;
    }

    .original-image,
    .preview-frame {
      width: 100%;
    }
  }
</style>
