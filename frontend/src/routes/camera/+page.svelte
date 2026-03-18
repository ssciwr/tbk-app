<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { authedFetch } from '$lib/api';
  import { requireAuthRedirect } from '$lib/auth';

  type PendingImageCase = {
    case_id: number;
    status: 'metadata_entered';
    metadata: {
      child_name: string;
      animal_name: string;
      broken_bone: boolean;
      qr_content: string;
    };
  };

  let cases: PendingImageCase[] = [];
  let selectedCaseId: number | null = null;
  let selectedCase: PendingImageCase | null = null;

  let loadingCases = true;
  let loadError = '';
  let actionMessage = '';

  let captureMessage = '';
  let uploadMessage = '';
  let cameraError = '';

  let videoEl: HTMLVideoElement | null = null;
  let stream: MediaStream | null = null;
  let pollHandle: ReturnType<typeof setInterval> | null = null;

  let capturedFile: File | null = null;
  let previewUrl = '';

  $: selectedCase = cases.find((pending) => pending.case_id === selectedCaseId) ?? null;

  async function startCamera(): Promise<void> {
    cameraError = '';
    if (!navigator.mediaDevices?.getUserMedia) {
      cameraError = 'Webcam API not available; use file upload instead.';
      return;
    }

    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: { ideal: 'environment' },
          aspectRatio: { ideal: 1 },
          width: { ideal: 1080 },
          height: { ideal: 1080 }
        },
        audio: false
      });

      const track = stream.getVideoTracks()[0];
      if (track) {
        try {
          await track.applyConstraints({
            aspectRatio: 1,
            width: { ideal: 1080 },
            height: { ideal: 1080 }
          });
        } catch {
          // Not all cameras/browsers support these constraints.
        }
      }

      if (videoEl) {
        videoEl.srcObject = stream;
        await videoEl.play();
      }
    } catch {
      cameraError = 'Could not access webcam; use file upload instead.';
    }
  }

  function stopCamera(): void {
    if (stream) {
      for (const track of stream.getTracks()) {
        track.stop();
      }
      stream = null;
    }
  }

  async function loadPendingCases(): Promise<void> {
    const response = await authedFetch('/api/cases/pending-image');
    if (!response.ok) {
      loadError = 'Failed to load cases waiting for image acquisition.';
      loadingCases = false;
      return;
    }

    const data = (await response.json()) as { cases: PendingImageCase[] };
    cases = data.cases;
    loadError = '';
    loadingCases = false;

    if (cases.length === 0) {
      selectedCaseId = null;
      return;
    }

    if (!selectedCaseId || !cases.some((item) => item.case_id === selectedCaseId)) {
      selectedCaseId = cases[0].case_id;
    }
  }

  function selectCase(caseId: number): void {
    selectedCaseId = caseId;
    actionMessage = '';
    uploadMessage = '';
  }

  async function discardCase(caseId: number): Promise<void> {
    actionMessage = '';
    uploadMessage = '';

    const response = await authedFetch(`/api/cases/${caseId}/pending-image`, {
      method: 'DELETE'
    });

    if (!response.ok) {
      actionMessage = `Failed to discard case ${caseId}.`;
      return;
    }

    if (selectedCaseId === caseId) {
      capturedFile = null;
      captureMessage = '';
      revokePreview();
    }

    actionMessage = `Case ${caseId} discarded.`;
    await loadPendingCases();
  }

  function revokePreview(): void {
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
      previewUrl = '';
    }
  }

  function setCaptured(file: File): void {
    capturedFile = file;
    revokePreview();
    previewUrl = URL.createObjectURL(file);
  }

  function discardCaptured(): void {
    capturedFile = null;
    captureMessage = '';
    revokePreview();
  }

  async function captureFromWebcam(): Promise<void> {
    captureMessage = '';
    if (!videoEl || videoEl.readyState < 2) {
      captureMessage = 'Camera frame not ready yet.';
      return;
    }

    const sourceWidth = videoEl.videoWidth;
    const sourceHeight = videoEl.videoHeight;
    if (!sourceWidth || !sourceHeight) {
      captureMessage = 'Camera frame has invalid dimensions.';
      return;
    }

    const side = Math.min(sourceWidth, sourceHeight);
    const sx = Math.floor((sourceWidth - side) / 2);
    const sy = Math.floor((sourceHeight - side) / 2);

    const canvas = document.createElement('canvas');
    canvas.width = side;
    canvas.height = side;
    const context = canvas.getContext('2d');
    if (!context) {
      captureMessage = 'Failed to capture frame.';
      return;
    }

    context.drawImage(videoEl, sx, sy, side, side, 0, 0, side, side);
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/png'));
    if (!blob) {
      captureMessage = 'Failed to encode captured image.';
      return;
    }

    setCaptured(new File([blob], `capture-${Date.now()}.png`, { type: 'image/png' }));
    captureMessage = 'Image captured.';
  }

  $: if (videoEl && stream && videoEl.srcObject !== stream) {
    videoEl.srcObject = stream;
    void videoEl.play();
  }

  function onFileChange(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (file) {
      setCaptured(file);
    }
  }

  async function submitImage(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    uploadMessage = '';

    if (!selectedCaseId) {
      uploadMessage = 'Select a case first.';
      return;
    }

    if (!capturedFile) {
      uploadMessage = 'Capture or upload an image first.';
      return;
    }

    const form = new FormData();
    form.append('file', capturedFile);

    const response = await authedFetch(`/api/cases/${selectedCaseId}/image`, {
      method: 'POST',
      body: form
    });

    if (!response.ok) {
      uploadMessage = `Failed to upload image for case ${selectedCaseId}.`;
      return;
    }

    await goto('/review');
  }

  onMount(async () => {
    const token = await requireAuthRedirect();
    if (!token) {
      return;
    }
    await Promise.all([startCamera(), loadPendingCases()]);
    pollHandle = setInterval(loadPendingCases, 2000);
  });

  onDestroy(() => {
    if (pollHandle) {
      clearInterval(pollHandle);
      pollHandle = null;
    }
    stopCamera();
    revokePreview();
  });
</script>

<div class="grid cols-2">
  <section class="card">
    <h1>Acquire Image</h1>
    <p>Select a case that is waiting for image acquisition.</p>

    {#if actionMessage}
      <p>{actionMessage}</p>
    {/if}
    {#if loadError}
      <p style="color:#b23a48;">{loadError}</p>
    {/if}

    {#if loadingCases}
      <p>Loading pending cases...</p>
    {:else if cases.length === 0}
      <p>No cases waiting for image acquisition.</p>
    {:else}
      <div class="pending-case-list">
        {#each cases as pending}
          <article class="pending-case-card" class:selected={pending.case_id === selectedCaseId}>
            <h2>Case #{pending.case_id}</h2>
            <p><strong>Child:</strong> {pending.metadata.child_name}</p>
            <p><strong>Animal:</strong> {pending.metadata.animal_name}</p>
            <p><strong>QR:</strong> {pending.metadata.qr_content}</p>
            <div class="case-actions">
              <button
                type="button"
                class="secondary"
                on:click={() => selectCase(pending.case_id)}
                disabled={pending.case_id === selectedCaseId}
              >
                {pending.case_id === selectedCaseId ? 'Selected' : 'Select'}
              </button>
              <button type="button" class="warn" on:click={() => discardCase(pending.case_id)}>
                Discard this case
              </button>
            </div>
          </article>
        {/each}
      </div>
    {/if}
  </section>

  <section class="card">
    <h2>Camera Feed</h2>
    {#if selectedCase}
      <p>
        Capturing for <strong>Case #{selectedCase.case_id}</strong>
        ({selectedCase.metadata.child_name} / {selectedCase.metadata.animal_name})
      </p>
    {:else}
      <p>Select a pending case to upload an image.</p>
    {/if}

    {#if previewUrl}
      <img class="preview captured-frame" src={previewUrl} alt="Captured teddy" />
    {:else}
      <div class="camera-feed">
        <video
          bind:this={videoEl}
          autoplay
          playsinline
          muted
          disablePictureInPicture
          disableRemotePlayback
          class="preview"
        ></video>
      </div>
    {/if}

    <div style="display:flex; gap:0.5rem; margin-top:0.8rem; flex-wrap:wrap;">
      <button type="button" on:click={previewUrl ? discardCaptured : captureFromWebcam}>
        {previewUrl ? 'Discard image' : 'Capture'}
      </button>
      <label class="secondary" style="display:inline-block; margin:0; padding:0.45rem 0.7rem; border-radius:8px; border:1px solid var(--border); cursor:pointer;">
        Upload File
        <input type="file" accept="image/*" on:change={onFileChange} style="display:none;" />
      </label>
    </div>

    <form on:submit={submitImage} style="margin-top:0.8rem;">
      <button type="submit" disabled={!selectedCase || !capturedFile}>Upload image for selected case</button>
    </form>

    {#if captureMessage}
      <p>{captureMessage}</p>
    {/if}
    {#if uploadMessage}
      <p>{uploadMessage}</p>
    {/if}
    {#if cameraError}
      <p style="color:#b23a48;">{cameraError}</p>
    {/if}
  </section>
</div>

<style>
  .pending-case-list {
    display: grid;
    gap: 0.8rem;
  }

  .pending-case-card {
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 0.7rem;
    background: #fff;
    display: grid;
    gap: 0.35rem;
  }

  .pending-case-card.selected {
    border-color: var(--accent);
    box-shadow: 0 0 0 2px rgba(14, 124, 123, 0.18);
    background: #f4fbfb;
  }

  .pending-case-card h2,
  .pending-case-card p {
    margin: 0;
  }

  .case-actions {
    margin-top: 0.35rem;
    display: flex;
    gap: 0.45rem;
    flex-wrap: wrap;
  }

  .camera-feed {
    border-radius: 10px;
    border: 1px solid var(--border);
    background: #121212;
    overflow: hidden;
  }

  .camera-feed video.preview {
    display: block;
    width: 100%;
    max-width: 100%;
    aspect-ratio: 1 / 1;
    object-fit: cover;
  }

  img.captured-frame {
    display: block;
    width: 100%;
    max-width: 100%;
    aspect-ratio: 1 / 1;
    object-fit: cover;
    border-radius: 10px;
    border: 1px solid var(--border);
    background: #121212;
    overflow: hidden;
  }
</style>
