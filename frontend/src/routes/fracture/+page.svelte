<script lang="ts">
  import { goto } from '$app/navigation';
  import { onDestroy, onMount } from 'svelte';
  import CaseNavigator from '$lib/components/CaseNavigator.svelte';
  import FractureEditorInline from '$lib/components/FractureEditorInline.svelte';
  import { authedFetch, authedFetchUrl, loadAppConfig } from '$lib/api';
  import { formatCaseSubject, hasText, isQrOnlyCase } from '$lib/caseDisplay';
  import { requireAuthRedirect } from '$lib/auth';

  type FinalizeAction = 'proceed_without_breaking' | 'apply_bone_breaking';
  type FinalizeRequest = {
    action: FinalizeAction;
    imageBlob?: Blob;
  };

  type ApiPendingFractureCase = {
    case_id: number;
    metadata: {
      child_name: string;
      animal_name: string;
      animal_type?: string;
    };
    selected_url: string;
  };

  type PendingFractureCase = Omit<ApiPendingFractureCase, 'selected_url'> & {
    selected_url: string | null;
  };

  let cases: PendingFractureCase[] = [];
  let selectedCaseId: number | null = null;
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

  async function decide(caseId: number, request: FinalizeRequest): Promise<void> {
    actionMessage = '';
    decidingCaseId = caseId;
    try {
      let response: Response;
      if (request.imageBlob) {
        const form = new FormData();
        form.append('image', request.imageBlob, `fracture-${caseId}.png`);
        response = await authedFetch(`/api/fracture/${caseId}/submit`, {
          method: 'POST',
          body: form
        });
      } else {
        response = await authedFetch(`/api/fracture/${caseId}/decision`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action: request.action })
        });
      }

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

<div class="card stage-intro">
  <h1>Bone Breaking Stage</h1>
  <p>Select a case, use the fracture editor, then finalize the result.</p>

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
  {/if}
</div>

{#if !loading && cases.length > 0}
  <div class="case-workspace">
    <CaseNavigator
      items={cases}
      bind:selectedCaseId
      itemLabel="cases"
      ariaLabel="Cases waiting for bone breaking"
    />

    <div class="fracture-detail">
      {#each cases as pending (pending.case_id)}
        <article class="card fracture-card" hidden={pending.case_id !== selectedCaseId}>
          <h2>Case #{pending.case_id}</h2>
          {#if hasText(pending.metadata.child_name)}
            <p><strong>Child:</strong> {pending.metadata.child_name}</p>
          {/if}
          {#if hasText(pending.metadata.animal_name)}
            <p><strong>Animal:</strong> {pending.metadata.animal_name}</p>
          {/if}
          {#if isQrOnlyCase(pending.metadata)}
            <p><strong>Mode:</strong> QR-only fast-track</p>
          {/if}
          <FractureEditorInline
            caseId={pending.case_id}
            caseLabel={formatCaseSubject(pending.metadata)}
            imageSrc={pending.selected_url}
            busy={decidingCaseId === pending.case_id}
            onFinalize={(request) => void decide(pending.case_id, request)}
          />
        </article>
      {/each}

      {#if selectedCaseId === null}
        <section class="card"><p>Select a case from the list.</p></section>
      {/if}
    </div>
  </div>
{/if}

<style>
  .stage-intro {
    margin-bottom: 1rem;
  }

  .stage-intro h1 {
    margin-top: 0;
  }

  .case-workspace {
    display: grid;
    grid-template-columns: minmax(220px, 280px) minmax(0, 1fr);
    gap: 1rem;
    align-items: start;
  }

  .fracture-detail {
    min-width: 0;
  }

  .fracture-card {
    display: grid;
    gap: 0.7rem;
    align-content: start;
    background: #fff;
  }

  .fracture-card[hidden] {
    display: none;
  }

  .fracture-card h2,
  .fracture-card p {
    margin: 0;
  }

  @media (max-width: 760px) {
    .case-workspace {
      grid-template-columns: 1fr;
    }
  }
</style>
