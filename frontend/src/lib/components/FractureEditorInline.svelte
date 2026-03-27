<script lang="ts">
  import { onDestroy } from 'svelte';

  export let caseId: number;
  export let caseLabel = '';
  export let imageSrc: string | null = null;
  export let busy = false;
  export let onFinalize: ((action: FinalizeAction) => void) | null = null;

  type FinalizeAction = 'proceed_without_breaking' | 'apply_bone_breaking';
  type BoneBreakComputation = {
    output: ImageData;
    erasedPixels: number;
  };

  const MASK_ALPHA_THRESHOLD = 32;
  const BONE_THRESHOLD_BIAS = -8;
  const BONE_GROW_THRESHOLD_BIAS = -20;
  const BONE_GROW_ITERATIONS = 2;
  const INTERFACE_GROW_ITERATIONS = 2;
  const DARK_SEED_BIAS = -12;
  const RELAXED_BACKGROUND_MARGIN = 6;
  const SMOOTHING_ITERATIONS = 12;

  let currentImageUrl: string | null = null;
  let baseImageUrl: string | null = null;
  let previewUrl: string | null = null;
  let sourceImageUrl: string | null = null;

  let message = '';
  let previewBusy = false;

  let tool: 'brush' | 'eraser' = 'brush';
  let brushSize = 14;

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

  function clampByte(value: number): number {
    if (value <= 0) {
      return 0;
    }
    if (value >= 255) {
      return 255;
    }
    return Math.round(value);
  }

  function luminanceFromRgb(r: number, g: number, b: number): number {
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  }

  function computeOtsuThreshold(histogram: Uint32Array, total: number): number {
    if (total <= 0) {
      return 128;
    }

    let weightedSum = 0;
    for (let tone = 0; tone < 256; tone += 1) {
      weightedSum += tone * histogram[tone];
    }

    let runningBackgroundWeight = 0;
    let runningBackgroundSum = 0;
    let maxVariance = -1;
    let threshold = 127;

    for (let tone = 0; tone < 256; tone += 1) {
      runningBackgroundWeight += histogram[tone];
      if (runningBackgroundWeight === 0) {
        continue;
      }

      const foregroundWeight = total - runningBackgroundWeight;
      if (foregroundWeight === 0) {
        break;
      }

      runningBackgroundSum += tone * histogram[tone];
      const backgroundMean = runningBackgroundSum / runningBackgroundWeight;
      const foregroundMean = (weightedSum - runningBackgroundSum) / foregroundWeight;
      const delta = backgroundMean - foregroundMean;
      const variance = runningBackgroundWeight * foregroundWeight * delta * delta;

      if (variance > maxVariance) {
        maxVariance = variance;
        threshold = tone;
      }
    }

    return threshold;
  }

  function breakBoneInMaskedArea(
    imageData: ImageData,
    overlayData: Uint8ClampedArray
  ): BoneBreakComputation {
    const width = imageData.width;
    const height = imageData.height;
    const pixels = width * height;
    const source = imageData.data;
    const luminance = new Float32Array(pixels);
    const userMask = new Uint8Array(pixels);
    const eraseMask = new Uint8Array(pixels);
    const histogram = new Uint32Array(256);

    let maskedPixelCount = 0;
    let minLuminance = 255;
    let maxLuminance = 0;
    let luminanceSum = 0;

    for (let index = 0; index < pixels; index += 1) {
      const pixelOffset = index * 4;
      const lightness = luminanceFromRgb(
        source[pixelOffset],
        source[pixelOffset + 1],
        source[pixelOffset + 2]
      );
      luminance[index] = lightness;

      if (overlayData[pixelOffset + 3] < MASK_ALPHA_THRESHOLD) {
        continue;
      }

      userMask[index] = 1;
      maskedPixelCount += 1;
      const bucket = clampByte(lightness);
      histogram[bucket] += 1;
      luminanceSum += lightness;
      minLuminance = Math.min(minLuminance, lightness);
      maxLuminance = Math.max(maxLuminance, lightness);
    }

    if (maskedPixelCount === 0) {
      return { output: imageData, erasedPixels: 0 };
    }

    const luminanceRange = maxLuminance - minLuminance;
    const baseThreshold =
      luminanceRange < 6
        ? luminanceSum / maskedPixelCount
        : computeOtsuThreshold(histogram, maskedPixelCount);
    const boneThreshold = Math.max(0, Math.min(255, baseThreshold + BONE_THRESHOLD_BIAS));
    const growThreshold = Math.max(0, Math.min(255, baseThreshold + BONE_GROW_THRESHOLD_BIAS));

    for (let index = 0; index < pixels; index += 1) {
      if (userMask[index] === 0) {
        continue;
      }
      if (luminance[index] >= boneThreshold) {
        eraseMask[index] = 1;
      }
    }

    const growMask = new Uint8Array(pixels);
    for (let iteration = 0; iteration < BONE_GROW_ITERATIONS; iteration += 1) {
      let changed = false;
      growMask.fill(0);

      for (let index = 0; index < pixels; index += 1) {
        if (userMask[index] === 0 || eraseMask[index] === 1 || luminance[index] < growThreshold) {
          continue;
        }

        const x = index % width;
        const hasErasedNeighbor =
          (x > 0 && eraseMask[index - 1] === 1) ||
          (x + 1 < width && eraseMask[index + 1] === 1) ||
          (index >= width && eraseMask[index - width] === 1) ||
          (index + width < pixels && eraseMask[index + width] === 1);

        if (!hasErasedNeighbor) {
          continue;
        }

        growMask[index] = 1;
        changed = true;
      }

      if (!changed) {
        break;
      }

      for (let index = 0; index < pixels; index += 1) {
        if (growMask[index] === 1) {
          eraseMask[index] = 1;
        }
      }
    }

    // Absorb the former bone/background transition band so residual contours do not remain visible.
    for (let iteration = 0; iteration < INTERFACE_GROW_ITERATIONS; iteration += 1) {
      let changed = false;
      growMask.fill(0);

      for (let index = 0; index < pixels; index += 1) {
        if (userMask[index] === 0 || eraseMask[index] === 1) {
          continue;
        }

        const x = index % width;
        const hasErasedNeighbor =
          (x > 0 && eraseMask[index - 1] === 1) ||
          (x + 1 < width && eraseMask[index + 1] === 1) ||
          (index >= width && eraseMask[index - width] === 1) ||
          (index + width < pixels && eraseMask[index + width] === 1);

        if (!hasErasedNeighbor) {
          continue;
        }

        growMask[index] = 1;
        changed = true;
      }

      if (!changed) {
        break;
      }

      for (let index = 0; index < pixels; index += 1) {
        if (growMask[index] === 1) {
          eraseMask[index] = 1;
        }
      }
    }

    const eraseIndices: number[] = [];
    for (let index = 0; index < pixels; index += 1) {
      if (eraseMask[index] === 1) {
        eraseIndices.push(index);
      }
    }

    if (eraseIndices.length === 0) {
      return { output: imageData, erasedPixels: 0 };
    }

    const seedMask = new Uint8Array(pixels);
    let seedCount = 0;
    const strictBackgroundLimit = Math.max(0, Math.min(255, baseThreshold + DARK_SEED_BIAS));

    for (let index = 0; index < pixels; index += 1) {
      if (eraseMask[index] === 1) {
        continue;
      }
      if (luminance[index] <= strictBackgroundLimit) {
        seedMask[index] = 1;
        seedCount += 1;
      }
    }

    if (seedCount === 0) {
      const relaxedBackgroundLimit = Math.min(255, baseThreshold + RELAXED_BACKGROUND_MARGIN);
      for (let index = 0; index < pixels; index += 1) {
        if (eraseMask[index] === 1 || seedMask[index] === 1) {
          continue;
        }
        if (luminance[index] <= relaxedBackgroundLimit) {
          seedMask[index] = 1;
          seedCount += 1;
        }
      }
    }

    if (seedCount === 0) {
      let darkest = 255;
      for (let index = 0; index < pixels; index += 1) {
        if (eraseMask[index] === 1) {
          continue;
        }
        darkest = Math.min(darkest, luminance[index]);
      }
      for (let index = 0; index < pixels; index += 1) {
        if (eraseMask[index] === 1) {
          continue;
        }
        if (luminance[index] <= darkest + 2) {
          seedMask[index] = 1;
          seedCount += 1;
        }
      }
    }

    if (seedCount === 0) {
      for (let index = 0; index < pixels; index += 1) {
        if (eraseMask[index] === 0) {
          seedMask[index] = 1;
          seedCount += 1;
        }
      }
    }

    const nearestSeed = new Int32Array(pixels);
    nearestSeed.fill(-1);
    const queue = new Int32Array(pixels);
    let head = 0;
    let tail = 0;

    for (let index = 0; index < pixels; index += 1) {
      if (seedMask[index] === 0) {
        continue;
      }
      nearestSeed[index] = index;
      queue[tail] = index;
      tail += 1;
    }

    // Propagate nearest background seed across the image so erased pixels can be rebuilt from dark tissue/background colors.
    while (head < tail) {
      const current = queue[head];
      head += 1;
      const seedIndex = nearestSeed[current];
      const x = current % width;

      if (x > 0) {
        const left = current - 1;
        if (nearestSeed[left] === -1) {
          nearestSeed[left] = seedIndex;
          queue[tail] = left;
          tail += 1;
        }
      }

      if (x + 1 < width) {
        const right = current + 1;
        if (nearestSeed[right] === -1) {
          nearestSeed[right] = seedIndex;
          queue[tail] = right;
          tail += 1;
        }
      }

      if (current >= width) {
        const up = current - width;
        if (nearestSeed[up] === -1) {
          nearestSeed[up] = seedIndex;
          queue[tail] = up;
          tail += 1;
        }
      }

      if (current + width < pixels) {
        const down = current + width;
        if (nearestSeed[down] === -1) {
          nearestSeed[down] = seedIndex;
          queue[tail] = down;
          tail += 1;
        }
      }
    }

    const output = new Uint8ClampedArray(source);
    const workR = new Float32Array(pixels);
    const workG = new Float32Array(pixels);
    const workB = new Float32Array(pixels);

    for (let index = 0; index < pixels; index += 1) {
      const pixelOffset = index * 4;
      workR[index] = output[pixelOffset];
      workG[index] = output[pixelOffset + 1];
      workB[index] = output[pixelOffset + 2];
    }

    for (const index of eraseIndices) {
      const seedIndex = nearestSeed[index] >= 0 ? nearestSeed[index] : index;
      const sourceOffset = seedIndex * 4;
      const pixelOffset = index * 4;
      output[pixelOffset] = source[sourceOffset];
      output[pixelOffset + 1] = source[sourceOffset + 1];
      output[pixelOffset + 2] = source[sourceOffset + 2];
      workR[index] = output[pixelOffset];
      workG[index] = output[pixelOffset + 1];
      workB[index] = output[pixelOffset + 2];
    }

    const nextR = new Float32Array(eraseIndices.length);
    const nextG = new Float32Array(eraseIndices.length);
    const nextB = new Float32Array(eraseIndices.length);

    // Smooth only inside the erased region (plus dark seeds) to blend texture while keeping a hard mask boundary against outside bone.
    for (let iteration = 0; iteration < SMOOTHING_ITERATIONS; iteration += 1) {
      for (let slot = 0; slot < eraseIndices.length; slot += 1) {
        const index = eraseIndices[slot];
        const x = index % width;
        const y = Math.floor(index / width);

        let sumR = workR[index] * 2.5;
        let sumG = workG[index] * 2.5;
        let sumB = workB[index] * 2.5;
        let sumWeight = 2.5;

        const minY = Math.max(0, y - 1);
        const maxY = Math.min(height - 1, y + 1);
        const minX = Math.max(0, x - 1);
        const maxX = Math.min(width - 1, x + 1);
        for (let scanY = minY; scanY <= maxY; scanY += 1) {
          for (let scanX = minX; scanX <= maxX; scanX += 1) {
            if (scanX === x && scanY === y) {
              continue;
            }

            const neighborIndex = scanY * width + scanX;
            if (eraseMask[neighborIndex] === 0 && seedMask[neighborIndex] === 0) {
              continue;
            }

            const weight = scanX === x || scanY === y ? 1 : 0.75;
            sumR += workR[neighborIndex] * weight;
            sumG += workG[neighborIndex] * weight;
            sumB += workB[neighborIndex] * weight;
            sumWeight += weight;
          }
        }

        nextR[slot] = sumR / sumWeight;
        nextG[slot] = sumG / sumWeight;
        nextB[slot] = sumB / sumWeight;
      }

      for (let slot = 0; slot < eraseIndices.length; slot += 1) {
        const index = eraseIndices[slot];
        workR[index] = nextR[slot];
        workG[index] = nextG[slot];
        workB[index] = nextB[slot];
      }
    }

    for (const index of eraseIndices) {
      const pixelOffset = index * 4;
      output[pixelOffset] = clampByte(workR[index]);
      output[pixelOffset + 1] = clampByte(workG[index]);
      output[pixelOffset + 2] = clampByte(workB[index]);
    }

    return {
      output: new ImageData(output, width, height),
      erasedPixels: eraseIndices.length
    };
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

  async function breakBone(): Promise<void> {
    if (!currentImageUrl || busy || !imageEl || !canvasEl || !canvasCtx) {
      return;
    }
    if (!overlayHasContent()) {
      message = 'Draw a mask over the bone first.';
      return;
    }

    previewBusy = true;
    message = '';
    try {
      const naturalWidth = Math.max(1, imageEl.naturalWidth || canvasEl.width);
      const naturalHeight = Math.max(1, imageEl.naturalHeight || canvasEl.height);

      const workCanvas = document.createElement('canvas');
      workCanvas.width = naturalWidth;
      workCanvas.height = naturalHeight;
      const workCtx = workCanvas.getContext('2d');
      if (!workCtx) {
        message = 'Failed to create working canvas.';
        return;
      }

      workCtx.drawImage(imageEl, 0, 0, naturalWidth, naturalHeight);
      const sourcePixels = workCtx.getImageData(0, 0, naturalWidth, naturalHeight);

      const overlayCanvas = document.createElement('canvas');
      overlayCanvas.width = naturalWidth;
      overlayCanvas.height = naturalHeight;
      const overlayCtx = overlayCanvas.getContext('2d');
      if (!overlayCtx) {
        message = 'Failed to create mask canvas.';
        return;
      }
      overlayCtx.drawImage(canvasEl, 0, 0, naturalWidth, naturalHeight);
      const overlayPixels = overlayCtx.getImageData(0, 0, naturalWidth, naturalHeight).data;

      const processed = breakBoneInMaskedArea(sourcePixels, overlayPixels);
      if (processed.erasedPixels === 0) {
        message = 'No bright bone pixels detected inside the mask.';
        return;
      }

      workCtx.putImageData(processed.output, 0, 0);
      const previewBlob = await canvasToBlob(workCanvas);
      if (!previewBlob) {
        message = 'Failed to export broken-bone preview.';
        return;
      }
      const nextPreviewUrl = URL.createObjectURL(previewBlob);
      if (previewUrl) {
        URL.revokeObjectURL(previewUrl);
      }
      previewUrl = nextPreviewUrl;
      currentImageUrl = nextPreviewUrl;
      undoStack = [];
      redoStack = [];
      clearOverlayDirect();
      message = `Case #${caseId}: bone removed in masked region (${processed.erasedPixels} px).`;
    } catch {
      message = 'Failed to break bone in selected mask.';
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
    <button type="button" class="ok" on:click={breakBone} disabled={previewBusy || busy || !currentImageUrl}>
      {previewBusy ? 'Breaking...' : 'Break bone'}
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
