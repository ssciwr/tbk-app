<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { authedFetch, authedFetchUrl } from '$lib/api';
  import { requireAuthRedirect } from '$lib/auth';

  type ApiPendingFractureCase = {
    case_id: number;
    metadata: {
      child_name: string;
      animal_name: string;
    };
    selected_url: string;
  };

  type PendingFractureCase = Omit<ApiPendingFractureCase, 'selected_url'> & {
    selected_url: string | null;
  };

  let cases: PendingFractureCase[] = [];
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

  async function loadPending(): Promise<void> {
    const response = await authedFetch('/api/fracture/pending');
    if (!response.ok) {
      error = 'Failed to load pending bone breaking cases.';
      loading = false;
      return;
    }

    const data = (await response.json()) as { cases: ApiPendingFractureCase[] };
    const nextObjectUrls: string[] = [];
    const hydrated = await Promise.all(
      data.cases.map(async (pending): Promise<PendingFractureCase> => {
        const selected = await toProtectedImageSrc(pending.selected_url, nextObjectUrls);
        return { ...pending, selected_url: selected };
      })
    );

    const previousObjectUrls = activeObjectUrls;
    activeObjectUrls = nextObjectUrls;
    revokeObjectUrls(previousObjectUrls);
    cases = hydrated;
    loading = false;
  }

  async function decide(caseId: number, action: 'proceed_without_breaking' | 'apply_bone_breaking'): Promise<void> {
    actionMessage = '';
    const response = await authedFetch(`/api/fracture/${caseId}/decision`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action })
    });

    if (!response.ok) {
      actionMessage = `Failed to submit case ${caseId}.`;
      return;
    }

    actionMessage = `Case ${caseId}: submitted successfully.`;
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
  <h1>Bone Breaking Stage</h1>
  <p>Finalize each accepted image by proceeding directly or applying the dummy bone breaking step.</p>

  {#if actionMessage}
    <p>{actionMessage}</p>
  {/if}
  {#if error}
    <p style="color:#b23a48;">{error}</p>
  {/if}

  {#if loading}
    <p>Loading pending cases...</p>
  {:else if cases.length === 0}
    <p>No cases waiting for bone breaking.</p>
  {:else}
    <div class="fracture-grid">
      {#each cases as pending}
        <article class="card fracture-card">
          <h2>Case #{pending.case_id}</h2>
          <p><strong>Child:</strong> {pending.metadata.child_name}</p>
          <p><strong>Animal:</strong> {pending.metadata.animal_name}</p>

          {#if pending.selected_url}
            <img class="preview fracture-image" src={pending.selected_url} alt={`Selected result for case ${pending.case_id}`} />
          {:else}
            <div class="preview-frame">Selected image unavailable</div>
          {/if}

          <button
            class="secondary"
            on:click={() => decide(pending.case_id, 'proceed_without_breaking')}
          >
            Proceed without breaking a bone
          </button>
          <button
            class="ok"
            on:click={() => decide(pending.case_id, 'apply_bone_breaking')}
          >
            Apply bone breaking
          </button>
        </article>
      {/each}
    </div>
  {/if}
</div>

<style>
  .fracture-grid {
    display: grid;
    gap: 1rem;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  }

  .fracture-card {
    display: grid;
    gap: 0.6rem;
    align-content: start;
    background: #fff;
  }

  .fracture-card h2,
  .fracture-card p {
    margin: 0;
  }

  .fracture-image {
    width: 100%;
    aspect-ratio: 1 / 1;
    object-fit: cover;
  }

  .preview-frame {
    width: 100%;
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
</style>
