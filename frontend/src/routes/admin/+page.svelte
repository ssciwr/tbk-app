<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { authedFetch } from '$lib/api';
  import { requireAuthRedirect } from '$lib/auth';

  type QRJobStatus = 'idle' | 'starting' | 'running' | 'done' | 'failed';
  type QRJobCreateResponse = {
    job_id: string;
    status: Exclude<QRJobStatus, 'idle' | 'starting'>;
  };
  type QRJobStateResponse = {
    status: Exclude<QRJobStatus, 'idle' | 'starting'>;
    progress: number;
    error?: string | null;
  };

  const POLL_INTERVAL_MS = 1000;

  let count = 50;
  let jobId = '';
  let status: QRJobStatus = 'idle';
  let progress = 0;
  let message = '';
  let pollToken = 0;
  let activePollController: AbortController | null = null;

  async function startJob(): Promise<void> {
    stopPolling();
    jobId = '';
    status = 'starting';
    progress = 0;
    message = '';

    try {
      const response = await authedFetch('/api/admin/qr-jobs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ count })
      });

      if (!response.ok) {
        status = 'idle';
        message = 'Failed to start QR generation job.';
        return;
      }

      const data = (await response.json()) as QRJobCreateResponse;
      jobId = data.job_id;
      status = data.status;
      startPolling(data.job_id);
    } catch {
      status = 'idle';
      message = 'Failed to start QR generation job.';
    }
  }

  async function fetchJobState(requestedJobId: string, signal: AbortSignal): Promise<boolean> {
    const response = await authedFetch(`/api/admin/qr-jobs/${requestedJobId}`, {
      cache: 'no-store',
      signal
    });
    if (!response.ok) {
      if (requestedJobId !== jobId || signal.aborted) {
        return false;
      }
      message = 'Failed to poll QR job state.';
      stopPolling();
      return false;
    }

    const data = (await response.json()) as QRJobStateResponse;
    if (requestedJobId !== jobId || signal.aborted) {
      return false;
    }

    status = data.status;
    progress = data.progress;
    message = status === 'failed' ? data.error ?? 'QR generation failed.' : '';

    if (status === 'done' || status === 'failed') {
      stopPolling();
      return false;
    }

    return true;
  }

  async function pollJob(requestedJobId: string, token: number): Promise<void> {
    while (jobId === requestedJobId && pollToken === token) {
      const controller = new AbortController();
      activePollController = controller;

      try {
        const shouldContinue = await fetchJobState(requestedJobId, controller.signal);
        if (!shouldContinue || jobId !== requestedJobId || pollToken !== token) {
          return;
        }
      } catch {
        if (controller.signal.aborted || jobId !== requestedJobId || pollToken !== token) {
          return;
        }
        message = 'Failed to poll QR job state.';
        stopPolling();
        return;
      } finally {
        if (activePollController === controller) {
          activePollController = null;
        }
      }

      await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
    }
  }

  function startPolling(requestedJobId: string): void {
    stopPolling();
    const token = ++pollToken;
    void pollJob(requestedJobId, token);
  }

  function stopPolling(): void {
    pollToken += 1;
    if (activePollController) {
      activePollController.abort();
      activePollController = null;
    }
  }

  async function downloadPdf(): Promise<void> {
    if (!jobId) {
      return;
    }

    const response = await authedFetch(`/api/admin/qr-jobs/${jobId}/pdf`);
    if (!response.ok) {
      message = 'PDF is not ready yet.';
      return;
    }

    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `qr-${jobId}.pdf`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  }

  onMount(async () => {
    const token = await requireAuthRedirect();
    if (!token) {
      return;
    }
  });

  onDestroy(() => stopPolling());
</script>

<div class="card">
  <h1>Admin: QR Batch Generator</h1>
  <label>
    Number of QR codes (1-1000)
    <input type="number" min="1" max="1000" bind:value={count} />
  </label>
  <div style="display:flex; gap:0.6rem; flex-wrap:wrap;">
    <button on:click={startJob}>Start Job</button>
    <button class="secondary" on:click={downloadPdf} disabled={status !== 'done'}>Download PDF</button>
  </div>

  <p>Status: <strong>{status}</strong></p>
  <div class="progress-row">
    <label for="qr-progress">Progress</label>
    <progress id="qr-progress" max="100" value={progress} aria-label="QR generation progress"></progress>
    <span>{progress}%</span>
  </div>

  {#if message}
    <p style="color:#b23a48;">{message}</p>
  {/if}
</div>

<style>
  .progress-row {
    display: grid;
    gap: 0.35rem;
    margin-top: 0.6rem;
  }

  progress {
    appearance: none;
    -webkit-appearance: none;
    width: 100%;
    height: 1rem;
    border: none;
    border-radius: 999px;
    overflow: hidden;
    background: #e6efe7;
  }

  progress::-webkit-progress-bar {
    background: #e6efe7;
  }

  progress::-webkit-progress-value {
    background: #1f9d55;
  }

  progress::-moz-progress-bar {
    background: #1f9d55;
  }
</style>
