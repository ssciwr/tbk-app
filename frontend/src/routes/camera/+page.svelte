<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { authedFetch } from '$lib/api';
  import { rememberProfiledCamera, startProfiledCamera } from '$lib/camera';
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
  let previewImageEl: HTMLImageElement | null = null;
  let cropOverlayEl: HTMLDivElement | null = null;

  type CropSquare = {
    x: number;
    y: number;
    size: number;
  };

  type CropCorner = 'tl' | 'tr' | 'br' | 'bl';
  type CropDragMode = 'draw' | 'move' | 'resize-tl' | 'resize-tr' | 'resize-br' | 'resize-bl' | null;

  let cropEditMode = false;
  let cropDragging = false;
  let cropStartX = 0;
  let cropStartY = 0;
  let cropSelection: CropSquare | null = null;
  let cropDragMode: CropDragMode = null;
  let cropMoveOffsetX = 0;
  let cropMoveOffsetY = 0;
  let cropResizeAnchorX = 0;
  let cropResizeAnchorY = 0;
  let cropHoverCorner: CropCorner | null = null;
  let cropHoverMove = false;
  let cropOverlayCursor = 'crosshair';

  $: selectedCase = cases.find((pending) => pending.case_id === selectedCaseId) ?? null;
  $: cropOverlayCursor = resolveCropOverlayCursor();

  async function startCamera(): Promise<void> {
    cameraError = '';
    if (!navigator.mediaDevices?.getUserMedia) {
      cameraError = 'Webcam API not available; use file upload instead.';
      return;
    }

    try {
      stream = await startProfiledCamera('camera', videoEl);
    } catch {
      cameraError = 'Could not access webcam; use file upload instead.';
    }
  }

  function stopCamera(): void {
    if (stream) {
      rememberProfiledCamera('camera', stream);
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
      resetCropEdit();
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
    previewImageEl = null;
    cropOverlayEl = null;
  }

  function resetCropEdit(): void {
    cropEditMode = false;
    cropDragging = false;
    cropDragMode = null;
    cropStartX = 0;
    cropStartY = 0;
    cropMoveOffsetX = 0;
    cropMoveOffsetY = 0;
    cropResizeAnchorX = 0;
    cropResizeAnchorY = 0;
    cropHoverCorner = null;
    cropHoverMove = false;
    cropSelection = null;
  }

  function setCaptured(file: File): void {
    resetCropEdit();
    capturedFile = file;
    revokePreview();
    previewUrl = URL.createObjectURL(file);
  }

  function discardCaptured(): void {
    resetCropEdit();
    capturedFile = null;
    captureMessage = '';
    revokePreview();
  }

  function startCropEdit(): void {
    if (!previewUrl) {
      return;
    }
    cropEditMode = true;
    cropDragging = false;
    cropSelection = null;
    captureMessage = 'Draw a square crop and confirm it.';
  }

  function cancelCropEdit(): void {
    resetCropEdit();
    captureMessage = 'Crop edit canceled.';
  }

  function cropPoint(event: PointerEvent): { x: number; y: number } | null {
    if (!cropOverlayEl) {
      return null;
    }
    const rect = cropOverlayEl.getBoundingClientRect();
    const x = Math.max(0, Math.min(rect.width, event.clientX - rect.left));
    const y = Math.max(0, Math.min(rect.height, event.clientY - rect.top));
    return { x, y };
  }

  function updateCropSelection(currentX: number, currentY: number): void {
    if (!cropOverlayEl) {
      return;
    }
    const rect = cropOverlayEl.getBoundingClientRect();
    const dx = currentX - cropStartX;
    const dy = currentY - cropStartY;
    const directionX = dx >= 0 ? 1 : -1;
    const directionY = dy >= 0 ? 1 : -1;
    const maxSideX = directionX > 0 ? rect.width - cropStartX : cropStartX;
    const maxSideY = directionY > 0 ? rect.height - cropStartY : cropStartY;
    const side = Math.min(Math.max(Math.abs(dx), Math.abs(dy)), maxSideX, maxSideY);
    const x = directionX > 0 ? cropStartX : cropStartX - side;
    const y = directionY > 0 ? cropStartY : cropStartY - side;
    cropSelection = {
      x,
      y,
      size: Math.max(1, side)
    };
  }

  function pointInsideCrop(point: { x: number; y: number }, selection: CropSquare): boolean {
    return (
      point.x >= selection.x &&
      point.x <= selection.x + selection.size &&
      point.y >= selection.y &&
      point.y <= selection.y + selection.size
    );
  }

  function cornerCursor(corner: CropCorner): string {
    return corner === 'tl' || corner === 'br' ? 'nwse-resize' : 'nesw-resize';
  }

  function resizeModeFromCorner(corner: CropCorner): Exclude<CropDragMode, 'draw' | 'move' | null> {
    return `resize-${corner}`;
  }

  function cornerFromResizeMode(mode: CropDragMode): CropCorner | null {
    if (mode === 'resize-tl') {
      return 'tl';
    }
    if (mode === 'resize-tr') {
      return 'tr';
    }
    if (mode === 'resize-br') {
      return 'br';
    }
    if (mode === 'resize-bl') {
      return 'bl';
    }
    return null;
  }

  function clearCropHoverState(): void {
    cropHoverCorner = null;
    cropHoverMove = false;
  }

  function resolveCropOverlayCursor(): string {
    if (cropDragMode === 'move') {
      return 'move';
    }
    const resizeCorner = cornerFromResizeMode(cropDragMode);
    if (resizeCorner) {
      return cornerCursor(resizeCorner);
    }
    if (cropHoverCorner) {
      return cornerCursor(cropHoverCorner);
    }
    if (cropHoverMove) {
      return 'move';
    }
    return 'crosshair';
  }

  function cropCornerAtPoint(point: { x: number; y: number }, selection: CropSquare): CropCorner | null {
    const threshold = 14;
    const thresholdSquared = threshold * threshold;
    const corners: Array<{ corner: CropCorner; x: number; y: number }> = [
      { corner: 'tl', x: selection.x, y: selection.y },
      { corner: 'tr', x: selection.x + selection.size, y: selection.y },
      { corner: 'br', x: selection.x + selection.size, y: selection.y + selection.size },
      { corner: 'bl', x: selection.x, y: selection.y + selection.size }
    ];

    let matchedCorner: CropCorner | null = null;
    let matchedDistance = Number.POSITIVE_INFINITY;
    for (const corner of corners) {
      const dx = point.x - corner.x;
      const dy = point.y - corner.y;
      const distanceSquared = dx * dx + dy * dy;
      if (distanceSquared <= thresholdSquared && distanceSquared < matchedDistance) {
        matchedCorner = corner.corner;
        matchedDistance = distanceSquared;
      }
    }
    return matchedCorner;
  }

  function updateCropHoverState(point: { x: number; y: number }): void {
    if (!cropSelection) {
      clearCropHoverState();
      return;
    }
    cropHoverCorner = cropCornerAtPoint(point, cropSelection);
    cropHoverMove = !cropHoverCorner && pointInsideCrop(point, cropSelection);
  }

  function setResizeAnchor(corner: CropCorner, selection: CropSquare): void {
    if (corner === 'tl') {
      cropResizeAnchorX = selection.x + selection.size;
      cropResizeAnchorY = selection.y + selection.size;
      return;
    }
    if (corner === 'tr') {
      cropResizeAnchorX = selection.x;
      cropResizeAnchorY = selection.y + selection.size;
      return;
    }
    if (corner === 'br') {
      cropResizeAnchorX = selection.x;
      cropResizeAnchorY = selection.y;
      return;
    }
    cropResizeAnchorX = selection.x + selection.size;
    cropResizeAnchorY = selection.y;
  }

  function updateMovedCropSelection(currentX: number, currentY: number): void {
    if (!cropOverlayEl || !cropSelection) {
      return;
    }
    const rect = cropOverlayEl.getBoundingClientRect();
    const nextX = currentX - cropMoveOffsetX;
    const nextY = currentY - cropMoveOffsetY;
    const maxX = Math.max(0, rect.width - cropSelection.size);
    const maxY = Math.max(0, rect.height - cropSelection.size);
    cropSelection = {
      x: Math.max(0, Math.min(maxX, nextX)),
      y: Math.max(0, Math.min(maxY, nextY)),
      size: cropSelection.size
    };
  }

  function updateResizedCropSelection(mode: CropDragMode, currentX: number, currentY: number): void {
    if (!cropOverlayEl || !cropSelection) {
      return;
    }
    const rect = cropOverlayEl.getBoundingClientRect();

    let maxSide = 1;
    let desiredSide = 1;
    let nextX = cropSelection.x;
    let nextY = cropSelection.y;

    if (mode === 'resize-tl') {
      maxSide = Math.max(1, Math.min(cropResizeAnchorX, cropResizeAnchorY));
      desiredSide = Math.max(cropResizeAnchorX - currentX, cropResizeAnchorY - currentY);
      const side = Math.max(1, Math.min(maxSide, desiredSide));
      nextX = cropResizeAnchorX - side;
      nextY = cropResizeAnchorY - side;
      cropSelection = { x: nextX, y: nextY, size: side };
      return;
    }

    if (mode === 'resize-tr') {
      maxSide = Math.max(1, Math.min(rect.width - cropResizeAnchorX, cropResizeAnchorY));
      desiredSide = Math.max(currentX - cropResizeAnchorX, cropResizeAnchorY - currentY);
      const side = Math.max(1, Math.min(maxSide, desiredSide));
      nextX = cropResizeAnchorX;
      nextY = cropResizeAnchorY - side;
      cropSelection = { x: nextX, y: nextY, size: side };
      return;
    }

    if (mode === 'resize-br') {
      maxSide = Math.max(1, Math.min(rect.width - cropResizeAnchorX, rect.height - cropResizeAnchorY));
      desiredSide = Math.max(currentX - cropResizeAnchorX, currentY - cropResizeAnchorY);
      const side = Math.max(1, Math.min(maxSide, desiredSide));
      nextX = cropResizeAnchorX;
      nextY = cropResizeAnchorY;
      cropSelection = { x: nextX, y: nextY, size: side };
      return;
    }

    if (mode === 'resize-bl') {
      maxSide = Math.max(1, Math.min(cropResizeAnchorX, rect.height - cropResizeAnchorY));
      desiredSide = Math.max(cropResizeAnchorX - currentX, currentY - cropResizeAnchorY);
      const side = Math.max(1, Math.min(maxSide, desiredSide));
      nextX = cropResizeAnchorX - side;
      nextY = cropResizeAnchorY;
      cropSelection = { x: nextX, y: nextY, size: side };
    }
  }

  function startCropSelection(event: PointerEvent): void {
    if (!cropEditMode || !cropOverlayEl || event.button !== 0) {
      return;
    }
    event.preventDefault();
    const point = cropPoint(event);
    if (!point) {
      return;
    }
    cropDragging = true;

    if (cropSelection) {
      const corner = cropCornerAtPoint(point, cropSelection);
      if (corner) {
        cropDragMode = resizeModeFromCorner(corner);
        setResizeAnchor(corner, cropSelection);
        cropHoverCorner = corner;
        cropHoverMove = false;
      } else if (pointInsideCrop(point, cropSelection)) {
        cropDragMode = 'move';
        cropMoveOffsetX = point.x - cropSelection.x;
        cropMoveOffsetY = point.y - cropSelection.y;
        cropHoverCorner = null;
        cropHoverMove = true;
      } else {
        cropDragMode = 'draw';
        cropStartX = point.x;
        cropStartY = point.y;
        cropSelection = { x: point.x, y: point.y, size: 1 };
        clearCropHoverState();
      }
    } else {
      cropDragMode = 'draw';
      cropStartX = point.x;
      cropStartY = point.y;
      cropSelection = { x: point.x, y: point.y, size: 1 };
      clearCropHoverState();
    }

    try {
      cropOverlayEl.setPointerCapture(event.pointerId);
    } catch {
      // Ignore browsers that do not support pointer capture.
    }
  }

  function continueCropSelection(event: PointerEvent): void {
    const point = cropPoint(event);
    if (!point) {
      return;
    }

    if (!cropDragging) {
      updateCropHoverState(point);
      return;
    }

    if (cropDragMode === 'move') {
      updateMovedCropSelection(point.x, point.y);
      return;
    }

    const resizeCorner = cornerFromResizeMode(cropDragMode);
    if (resizeCorner) {
      updateResizedCropSelection(cropDragMode, point.x, point.y);
      cropHoverCorner = resizeCorner;
      cropHoverMove = false;
      return;
    }

    updateCropSelection(point.x, point.y);
  }

  function finishCropSelection(event: PointerEvent): void {
    if (!cropDragging) {
      const point = cropPoint(event);
      if (point) {
        updateCropHoverState(point);
      }
      return;
    }
    cropDragging = false;
    cropDragMode = null;
    if (cropOverlayEl) {
      try {
        cropOverlayEl.releasePointerCapture(event.pointerId);
      } catch {
        // Ignore browsers that do not support pointer capture release.
      }
    }
    const point = cropPoint(event);
    if (point) {
      updateCropHoverState(point);
    } else {
      clearCropHoverState();
    }
  }

  function leaveCropOverlay(): void {
    if (cropDragging) {
      return;
    }
    clearCropHoverState();
  }

  async function loadImageFromFile(file: File): Promise<HTMLImageElement> {
    const objectUrl = URL.createObjectURL(file);
    try {
      const image = new Image();
      await new Promise<void>((resolve, reject) => {
        image.onload = () => resolve();
        image.onerror = () => reject(new Error('Failed to load image for cropping.'));
        image.src = objectUrl;
      });
      return image;
    } finally {
      URL.revokeObjectURL(objectUrl);
    }
  }

  async function confirmCropEdit(): Promise<void> {
    if (!capturedFile || !previewImageEl) {
      captureMessage = 'Capture an image before editing.';
      return;
    }

    if (!cropSelection || cropSelection.size < 8) {
      captureMessage = 'Draw a larger square crop first.';
      return;
    }

    try {
      const image = await loadImageFromFile(capturedFile);
      const displayWidth = Math.max(1, previewImageEl.clientWidth);
      const displayHeight = Math.max(1, previewImageEl.clientHeight);

      const scaleX = image.naturalWidth / displayWidth;
      const scaleY = image.naturalHeight / displayHeight;
      const sourceX = Math.max(0, Math.round(cropSelection.x * scaleX));
      const sourceY = Math.max(0, Math.round(cropSelection.y * scaleY));
      const requestedSide = Math.round(cropSelection.size * Math.min(scaleX, scaleY));
      const maxSide = Math.min(image.naturalWidth - sourceX, image.naturalHeight - sourceY);
      const side = Math.max(1, Math.min(requestedSide, maxSide));

      if (side < 8) {
        captureMessage = 'Crop area is too small.';
        return;
      }

      const canvas = document.createElement('canvas');
      canvas.width = side;
      canvas.height = side;
      const context = canvas.getContext('2d');
      if (!context) {
        captureMessage = 'Failed to prepare cropped image.';
        return;
      }

      context.drawImage(image, sourceX, sourceY, side, side, 0, 0, side, side);
      const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/png'));
      if (!blob) {
        captureMessage = 'Failed to encode cropped image.';
        return;
      }

      setCaptured(new File([blob], `capture-${Date.now()}.png`, { type: 'image/png' }));
      captureMessage = 'Image cropped.';
    } catch {
      captureMessage = 'Failed to crop image.';
      return;
    }

    resetCropEdit();
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
      <div class="captured-preview">
        <img bind:this={previewImageEl} class="preview captured-frame" src={previewUrl} alt="Captured teddy" />
        {#if cropEditMode}
          <div
            bind:this={cropOverlayEl}
            class="crop-overlay"
            style={`cursor:${cropOverlayCursor};`}
            role="application"
            aria-label="Crop selection area"
            on:pointerdown={startCropSelection}
            on:pointermove={continueCropSelection}
            on:pointerup={finishCropSelection}
            on:pointercancel={finishCropSelection}
            on:pointerleave={leaveCropOverlay}
          >
            {#if cropSelection}
              <div
                class="crop-selection"
                style={`left:${cropSelection.x}px;top:${cropSelection.y}px;width:${cropSelection.size}px;height:${cropSelection.size}px;`}
              >
                <div class="crop-handle tl"></div>
                <div class="crop-handle tr"></div>
                <div class="crop-handle br"></div>
                <div class="crop-handle bl"></div>
              </div>
            {/if}
          </div>
          <button
            type="button"
            class="secondary preview-corner-button confirm-crop-button"
            on:click={confirmCropEdit}
            disabled={!cropSelection || cropSelection.size < 8}
            aria-label="Confirm crop"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M9 16.17 4.83 12 3.41 13.41 9 19 21 7 19.59 5.59z"></path>
            </svg>
          </button>
          <button
            type="button"
            class="secondary preview-corner-button cancel-crop-button"
            on:click={cancelCropEdit}
            aria-label="Cancel edit"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M18.3 5.71 12 12l6.3 6.29-1.42 1.42L10.59 13.4 4.29 19.71 2.87 18.3 9.17 12 2.87 5.71 4.29 4.29l6.3 6.3 6.29-6.3z"></path>
            </svg>
          </button>
        {:else}
          <button
            type="button"
            class="secondary preview-corner-button edit-crop-button"
            on:click={startCropEdit}
            aria-label="Edit crop"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path
                d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zm2.92 2.33H5v-.92l9.06-9.06.92.92-9.06 9.06zM20.71 7.04a1.003 1.003 0 0 0 0-1.42L18.37 3.29a1.003 1.003 0 0 0-1.42 0L15.13 5.1l3.75 3.75 1.83-1.81z"
              ></path>
            </svg>
          </button>
        {/if}
      </div>
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
      <button type="button" on:click={previewUrl ? discardCaptured : captureFromWebcam} disabled={cropEditMode}>
        {previewUrl ? 'Discard image' : 'Capture'}
      </button>
      <label
        class="secondary upload-file-label"
        class:disabled={cropEditMode}
        style="display:inline-block; margin:0; padding:0.45rem 0.7rem; border-radius:8px; border:1px solid var(--border); cursor:pointer;"
      >
        Upload File
        <input type="file" accept="image/*" on:change={onFileChange} style="display:none;" disabled={cropEditMode} />
      </label>
    </div>

    <form on:submit={submitImage} style="margin-top:0.8rem;">
      <button type="submit" disabled={!selectedCase || !capturedFile || cropEditMode}>
        Upload image for selected case
      </button>
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

  .captured-preview {
    position: relative;
    border-radius: 10px;
    overflow: hidden;
  }

  .preview-corner-button {
    position: absolute;
    top: 0.65rem;
    right: 0.65rem;
    width: 2rem;
    height: 2rem;
    padding: 0.35rem;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border-radius: 999px;
    z-index: 3;
    backdrop-filter: blur(2px);
  }

  .edit-crop-button {
    opacity: 0;
    pointer-events: none;
    transition: opacity 120ms ease-in-out;
  }

  .captured-preview:hover .edit-crop-button,
  .captured-preview:focus-within .edit-crop-button {
    opacity: 1;
    pointer-events: auto;
  }

  .confirm-crop-button {
    pointer-events: auto;
  }

  .confirm-crop-button:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .cancel-crop-button {
    right: 3.1rem;
    pointer-events: auto;
  }

  .preview-corner-button svg {
    width: 1rem;
    height: 1rem;
    fill: currentColor;
  }

  .crop-overlay {
    position: absolute;
    inset: 0;
    cursor: crosshair;
    touch-action: none;
    user-select: none;
    z-index: 2;
  }

  .crop-selection {
    position: absolute;
    border: 2px solid #fff;
    background: rgba(255, 255, 255, 0.08);
    box-shadow: 0 0 0 9999px rgba(0, 0, 0, 0.42);
    pointer-events: none;
  }

  .crop-handle {
    position: absolute;
    width: 0.72rem;
    height: 0.72rem;
    border-radius: 999px;
    border: 2px solid #fff;
    background: rgba(14, 124, 123, 0.9);
    box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.35);
  }

  .crop-handle.tl {
    left: 0;
    top: 0;
    transform: translate(-50%, -50%);
  }

  .crop-handle.tr {
    right: 0;
    top: 0;
    transform: translate(50%, -50%);
  }

  .crop-handle.br {
    right: 0;
    bottom: 0;
    transform: translate(50%, 50%);
  }

  .crop-handle.bl {
    left: 0;
    bottom: 0;
    transform: translate(-50%, 50%);
  }

  .upload-file-label.disabled {
    opacity: 0.6;
    pointer-events: none;
  }
</style>
