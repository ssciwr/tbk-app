<script lang="ts">
  import { onDestroy } from 'svelte';
  import { authedFetch } from '$lib/api';

  export let caseId: number;
  export let caseLabel = '';
  export let imageSrc: string | null = null;
  export let busy = false;
  export let onFinalize: ((action: FinalizeAction) => void) | null = null;

  type FinalizeAction = 'proceed_without_breaking' | 'apply_bone_breaking';

  let currentImageUrl: string | null = null;
  let baseImageUrl: string | null = null;
  let previewUrl: string | null = null;
  let sourceImageUrl: string | null = null;

  let message = '';
  let previewBusy = false;

  let tool: 'brush' | 'eraser' = 'brush';
  let brushSize = 14;
  let fractureScale = 1.0;
  let fractureNoise = 10;

  let imageEl: HTMLImageElement | null = null;
  let canvasEl: HTMLCanvasElement | null = null;
  let canvasCtx: CanvasRenderingContext2D | null = null;
  let drawing = false;
  let lastX = 0;
  let lastY = 0;
  let undoStack: string[] = [];
  let redoStack: string[] = [];

  $: if (imageSrc !== sourceImageUrl) {
    sourceImageUrl = imageSrc;
    baseImageUrl = imageSrc;
    currentImageUrl = imageSrc;
    message = '';
    tool = 'brush';
    brushSize = 14;
    fractureScale = 1.0;
    fractureNoise = 10;
    undoStack = [];
    redoStack = [];
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
      previewUrl = null;
    }
    clearOverlayDirect();
  }

  function clearOverlayDirect(): void {
    if (!canvasEl || !canvasCtx) {
      return;
    }
    canvasCtx.save();
    canvasCtx.globalCompositeOperation = 'source-over';
    canvasCtx.clearRect(0, 0, canvasEl.width, canvasEl.height);
    canvasCtx.restore();
  }

  function snapshotOverlay(): string | null {
    if (!canvasEl) {
      return null;
    }
    try {
      return canvasEl.toDataURL('image/png');
    } catch {
      return null;
    }
  }

  function pushUndoSnapshot(): void {
    const snapshot = snapshotOverlay();
    if (!snapshot) {
      return;
    }
    undoStack = [...undoStack, snapshot];
    if (undoStack.length > 30) {
      undoStack = undoStack.slice(undoStack.length - 30);
    }
    redoStack = [];
  }

  function restoreOverlay(snapshot: string): void {
    if (!canvasEl || !canvasCtx) {
      return;
    }
    const image = new Image();
    image.onload = () => {
      if (!canvasEl || !canvasCtx) {
        return;
      }
      canvasCtx.save();
      canvasCtx.globalCompositeOperation = 'source-over';
      canvasCtx.clearRect(0, 0, canvasEl.width, canvasEl.height);
      canvasCtx.drawImage(image, 0, 0, canvasEl.width, canvasEl.height);
      canvasCtx.restore();
    };
    image.src = snapshot;
  }

  function undoOverlay(): void {
    if (undoStack.length === 0) {
      return;
    }
    const current = snapshotOverlay();
    const previous = undoStack[undoStack.length - 1];
    undoStack = undoStack.slice(0, undoStack.length - 1);
    if (current) {
      redoStack = [...redoStack, current];
    }
    restoreOverlay(previous);
  }

  function redoOverlay(): void {
    if (redoStack.length === 0) {
      return;
    }
    const current = snapshotOverlay();
    const next = redoStack[redoStack.length - 1];
    redoStack = redoStack.slice(0, redoStack.length - 1);
    if (current) {
      undoStack = [...undoStack, current];
    }
    restoreOverlay(next);
  }

  function clearOverlay(): void {
    pushUndoSnapshot();
    clearOverlayDirect();
  }

  function syncCanvasToImage(): void {
    if (!imageEl || !canvasEl) {
      return;
    }
    const width = Math.max(1, Math.round(imageEl.clientWidth));
    const height = Math.max(1, Math.round(imageEl.clientHeight));
    canvasEl.width = width;
    canvasEl.height = height;
    canvasCtx = canvasEl.getContext('2d');
    clearOverlayDirect();
  }

  function canvasPoint(event: PointerEvent): { x: number; y: number } {
    if (!canvasEl) {
      return { x: 0, y: 0 };
    }
    const rect = canvasEl.getBoundingClientRect();
    const x = Math.max(0, Math.min(rect.width, event.clientX - rect.left));
    const y = Math.max(0, Math.min(rect.height, event.clientY - rect.top));
    return { x, y };
  }

  function drawStroke(fromX: number, fromY: number, toX: number, toY: number): void {
    if (!canvasCtx) {
      return;
    }
    canvasCtx.save();
    canvasCtx.globalCompositeOperation = tool === 'eraser' ? 'destination-out' : 'source-over';
    canvasCtx.lineCap = 'round';
    canvasCtx.lineJoin = 'round';
    canvasCtx.strokeStyle = '#f2485a';
    canvasCtx.lineWidth = Math.max(1, brushSize);
    canvasCtx.beginPath();
    canvasCtx.moveTo(fromX, fromY);
    canvasCtx.lineTo(toX, toY);
    canvasCtx.stroke();
    canvasCtx.restore();
  }

  function startDrawing(event: PointerEvent): void {
    if (!canvasEl || event.button !== 0) {
      return;
    }
    event.preventDefault();
    pushUndoSnapshot();
    drawing = true;
    try {
      canvasEl.setPointerCapture(event.pointerId);
    } catch {
      // Not all browsers support pointer capture.
    }
    const point = canvasPoint(event);
    lastX = point.x;
    lastY = point.y;
    drawStroke(point.x, point.y, point.x, point.y);
  }

  function continueDrawing(event: PointerEvent): void {
    if (!drawing) {
      return;
    }
    const point = canvasPoint(event);
    drawStroke(lastX, lastY, point.x, point.y);
    lastX = point.x;
    lastY = point.y;
  }

  function stopDrawing(event: PointerEvent): void {
    if (!canvasEl) {
      drawing = false;
      return;
    }
    drawing = false;
    try {
      canvasEl.releasePointerCapture(event.pointerId);
    } catch {
      // Ignore browsers that do not support pointer capture release.
    }
  }

  async function canvasToBlob(canvas: HTMLCanvasElement): Promise<Blob | null> {
    return new Promise((resolve) => {
      canvas.toBlob((blob) => resolve(blob), 'image/png');
    });
  }

  function overlayHasContent(): boolean {
    if (!canvasEl || !canvasCtx) {
      return false;
    }
    const pixelData = canvasCtx.getImageData(0, 0, canvasEl.width, canvasEl.height).data;
    for (let index = 3; index < pixelData.length; index += 4) {
      if (pixelData[index] > 0) {
        return true;
      }
    }
    return false;
  }

  function resetPreview(): void {
    if (!baseImageUrl) {
      return;
    }
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
      previewUrl = null;
    }
    currentImageUrl = baseImageUrl;
    undoStack = [];
    redoStack = [];
    clearOverlayDirect();
    message = 'Reset to selected image.';
  }

  async function applyPreview(): Promise<void> {
    if (!currentImageUrl || busy) {
      return;
    }

    previewBusy = true;
    message = '';
    try {
      const imageResponse = await fetch(currentImageUrl);
      if (!imageResponse.ok) {
        message = 'Failed to prepare preview image.';
        return;
      }
      const imageBlob = await imageResponse.blob();

      const form = new FormData();
      form.append('image', imageBlob, `case-${caseId}.png`);

      if (canvasEl && overlayHasContent()) {
        const overlayBlob = await canvasToBlob(canvasEl);
        if (overlayBlob) {
          form.append('overlay', overlayBlob, `overlay-${caseId}.png`);
        }
      }

      form.append('x', '0');
      form.append('y', '0');
      form.append('scale', String(Number(fractureScale).toFixed(2)));
      form.append('noise', String(Math.round(Number(fractureNoise))));

      const response = await authedFetch('/api/fracture/preview', {
        method: 'POST',
        body: form
      });

      if (!response.ok) {
        message = 'Failed to apply fracture preview.';
        return;
      }

      const previewBlob = await response.blob();
      const nextPreviewUrl = URL.createObjectURL(previewBlob);
      if (previewUrl) {
        URL.revokeObjectURL(previewUrl);
      }
      previewUrl = nextPreviewUrl;
      currentImageUrl = nextPreviewUrl;
      undoStack = [];
      redoStack = [];
      clearOverlayDirect();
      message = 'Preview updated.';
    } catch {
      message = 'Failed to apply fracture preview.';
    } finally {
      previewBusy = false;
    }
  }

  function emitFinalize(action: FinalizeAction): void {
    if (busy || previewBusy) {
      return;
    }
    onFinalize?.(action);
  }

  onDestroy(() => {
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
    }
  });
</script>

<div class="editor-shell">
  <p class="editor-label">Editor: {caseLabel}</p>

  <div class="editor-toolbar">
    <button type="button" class:active={tool === 'brush'} on:click={() => (tool = 'brush')}>
      Brush
    </button>
    <button type="button" class:active={tool === 'eraser'} on:click={() => (tool = 'eraser')}>
      Eraser
    </button>
    <label class="editor-control">
      Brush size
      <input type="range" min="1" max="64" step="1" bind:value={brushSize} />
      <span>{Math.round(Number(brushSize))} px</span>
    </label>
    <label class="editor-control">
      Scale
      <input type="range" min="0.5" max="2" step="0.05" bind:value={fractureScale} />
      <span>{Number(fractureScale).toFixed(2)}</span>
    </label>
    <label class="editor-control">
      Noise
      <input type="range" min="0" max="40" step="1" bind:value={fractureNoise} />
      <span>{Math.round(Number(fractureNoise))}</span>
    </label>
  </div>

  <div class="editor-actions">
    <button type="button" class="secondary" on:click={undoOverlay} disabled={undoStack.length === 0}>
      Undo
    </button>
    <button type="button" class="secondary" on:click={redoOverlay} disabled={redoStack.length === 0}>
      Redo
    </button>
    <button type="button" class="secondary" on:click={clearOverlay}>Clear Overlay</button>
    <button type="button" class="secondary" on:click={resetPreview}>Reset Preview</button>
    <button type="button" class="ok" on:click={applyPreview} disabled={previewBusy || busy || !currentImageUrl}>
      {previewBusy ? 'Applying...' : 'Apply Preview'}
    </button>
  </div>

  <div class="editor-stage">
    {#if currentImageUrl}
      <div class="editor-frame">
        <img
          bind:this={imageEl}
          class="editor-image"
          src={currentImageUrl}
          alt="Fracture editor preview"
          on:load={syncCanvasToImage}
        />
        <canvas
          bind:this={canvasEl}
          class="editor-canvas"
          on:pointerdown={startDrawing}
          on:pointermove={continueDrawing}
          on:pointerup={stopDrawing}
          on:pointerleave={stopDrawing}
          on:pointercancel={stopDrawing}
        ></canvas>
      </div>
    {:else}
      <div class="preview-frame">Selected image unavailable</div>
    {/if}
  </div>

  <div class="editor-footer">
    <button
      type="button"
      class="secondary"
      on:click={() => emitFinalize('proceed_without_breaking')}
      disabled={busy || previewBusy}
    >
      Finalize without breaking
    </button>
    <button
      type="button"
      class="ok"
      on:click={() => emitFinalize('apply_bone_breaking')}
      disabled={busy || previewBusy}
    >
      Finalize with bone breaking
    </button>
  </div>

  {#if message}
    <p class="editor-message">{message}</p>
  {/if}
</div>

<style>
  .editor-shell {
    display: grid;
    gap: 0.7rem;
  }

  .editor-label {
    margin: 0;
    font-size: 0.92rem;
    color: #4f5358;
  }

  .editor-toolbar {
    display: flex;
    flex-wrap: wrap;
    gap: 0.6rem;
    align-items: center;
  }

  .editor-toolbar button.active {
    border-color: var(--accent);
    box-shadow: 0 0 0 2px rgba(14, 124, 123, 0.18);
  }

  .editor-control {
    margin: 0;
    display: grid;
    gap: 0.2rem;
    min-width: 170px;
  }

  .editor-control span {
    font-size: 0.85rem;
    color: #505050;
  }

  .editor-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
  }

  .editor-stage {
    display: grid;
    place-items: center;
    min-height: 260px;
    background: #f2f4f5;
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 0.7rem;
  }

  .editor-frame {
    position: relative;
    display: inline-block;
    max-width: 100%;
  }

  .editor-image {
    display: block;
    max-width: min(100%, 900px);
    max-height: 54vh;
    object-fit: contain;
    border-radius: 10px;
    border: 1px solid var(--border);
    background: #fff;
  }

  .editor-canvas {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    touch-action: none;
    cursor: crosshair;
    border-radius: 10px;
  }

  .editor-footer {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
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

  .editor-message {
    margin: 0;
  }
</style>
