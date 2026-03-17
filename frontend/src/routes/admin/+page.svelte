<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { authedFetch } from '$lib/api';
  import { requireAuthRedirect } from '$lib/auth';

  let count = 50;
  let jobId = '';
  let status = 'idle';
  let progress = 0;
  let message = '';
  let pollHandle: ReturnType<typeof setInterval> | null = null;

  async function startJob(): Promise<void> {
    message = '';
    const response = await authedFetch('/api/admin/qr-jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ count })
    });

    if (!response.ok) {
      message = 'Failed to start QR generation job.';
      return;
    }

    const data = await response.json();
    jobId = data.job_id;
    status = data.status;
    progress = 0;
    startPolling();
  }

  async function fetchJobState(): Promise<void> {
    if (!jobId) {
      return;
    }

    const response = await authedFetch(`/api/admin/qr-jobs/${jobId}`);
    if (!response.ok) {
      message = 'Failed to poll QR job state.';
      stopPolling();
      return;
    }

    const data = await response.json();
    status = data.status;
    progress = data.progress;

    if (status === 'done' || status === 'failed') {
      stopPolling();
    }
  }

  function startPolling(): void {
    stopPolling();
    pollHandle = setInterval(fetchJobState, 1000);
    fetchJobState();
  }

  function stopPolling(): void {
    if (pollHandle) {
      clearInterval(pollHandle);
      pollHandle = null;
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
