<script lang="ts">
  import { goto } from '$app/navigation';
  import { onDestroy, onMount } from 'svelte';
  import FractureEditorInline from '$lib/components/FractureEditorInline.svelte';
  import { authedFetch, authedFetchUrl, loadAppConfig } from '$lib/api';
  import { requireAuthRedirect } from '$lib/auth';

  type FinalizeAction = 'proceed_without_breaking' | 'apply_bone_breaking';

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
  let decidingCaseId: number | null = null;
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

  async function decide(caseId: number, action: FinalizeAction): Promise<void> {
    actionMessage = '';
    decidingCaseId = caseId;
    try {
      const response = await authedFetch(`/api/fracture/${caseId}/decision`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action })
      });

      if (!response.ok) {
        actionMessage = `Failed to submit case ${caseId}.`;
        return;
      }

      await goto('/results');
    } finally {
      decidingCaseId = null;
    }
  }

  onMount(async () => {
    const token = await requireAuthRedirect();
    if (!token) {
      return;
    }

    const config = await loadAppConfig();
    if (!config.fracture_editor_enabled) {
      await goto('/results');
      return;
    }

    await loadPending();
    pollHandle = setInterval(() => {
      if (!loading && cases.length === 0) {
        void loadPending();
      }
    }, 2000);
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
  <p>Use the fracture editor directly below each selected image, then finalize the case.</p>

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
          <FractureEditorInline
            caseId={pending.case_id}
            caseLabel={`${pending.metadata.child_name} / ${pending.metadata.animal_name}`}
            imageSrc={pending.selected_url}
            busy={decidingCaseId === pending.case_id}
            onFinalize={(action) => void decide(pending.case_id, action)}
          />
        </article>
      {/each}
    </div>
  {/if}
</div>

<style>
  .fracture-grid {
    display: grid;
    gap: 1rem;
    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  }

  .fracture-card {
    display: grid;
    gap: 0.7rem;
    align-content: start;
    background: #fff;
  }

  .fracture-card h2,
  .fracture-card p {
    margin: 0;
  }
</style>
