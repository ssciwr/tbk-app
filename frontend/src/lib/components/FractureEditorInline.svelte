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
  let sizeSliderOpen = false;

  let imageEl: HTMLImageElement | null = null;
  let canvasEl: HTMLCanvasElement | null = null;
  let canvasCtx: CanvasRenderingContext2D | null = null;
  let drawing = false;
  let lastX = 0;
  let lastY = 0;

  $: if (imageSrc !== sourceImageUrl) {
    sourceImageUrl = imageSrc;
    baseImageUrl = imageSrc;
    currentImageUrl = imageSrc;
    message = '';
    tool = 'brush';
    brushSize = 14;
    sizeSliderOpen = false;
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
    if (!canvasEl) {
      return;
    }
    if (sizeSliderOpen) {
      sizeSliderOpen = false;
      return;
    }
    if (event.button !== 0) {
      return;
    }
    event.preventDefault();
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
    sizeSliderOpen = false;
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

  function selectTool(nextTool: 'brush' | 'eraser'): void {
    if (busy || previewBusy) {
      return;
    }
    tool = nextTool;
    sizeSliderOpen = true;
  }

  function cancelEdits(): void {
    if (busy || previewBusy) {
      return;
    }
    resetPreview();
  }

  function acceptCurrentImage(): void {
    emitFinalize('proceed_without_breaking');
  }

  onDestroy(() => {
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
    }
  });
</script>

<div class="editor-shell">
  <p class="editor-label">Editor: {caseLabel}</p>

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

        <div class="editor-overlay-controls">
          <button
            type="button"
            class="secondary editor-icon-button"
            class:active={tool === 'brush'}
            on:click={() => selectTool('brush')}
            disabled={busy || previewBusy}
            aria-label="Brush tool"
            title="Brush"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path
                d="m15.88 3.29-7.6 7.6 4.24 4.24 7.6-7.6a1 1 0 0 0 0-1.42l-2.82-2.82a1 1 0 0 0-1.42 0ZM4.5 14.5a3.5 3.5 0 0 0-3.5 3.5c0 1.9 1.65 3.5 4 3.5 2.44 0 4.5-2.06 4.5-4.5A2.5 2.5 0 0 0 7 14.5H4.5Z"
              ></path>
            </svg>
          </button>
          <button
            type="button"
            class="secondary editor-icon-button"
            class:active={tool === 'eraser'}
            on:click={() => selectTool('eraser')}
            disabled={busy || previewBusy}
            aria-label="Eraser tool"
            title="Eraser"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path
                d="m12.23 3.17-9.06 9.06a2.25 2.25 0 0 0 0 3.18l4.24 4.24A2.25 2.25 0 0 0 9 20.34h.76l10.07-10.07a2.25 2.25 0 0 0 0-3.18l-4.42-4.42a2.25 2.25 0 0 0-3.18 0Zm6 5.51L9.31 17.6h-.38a.75.75 0 0 1-.53-.22l-3.96-3.96a.75.75 0 0 1 0-1.06l8.53-8.53a.75.75 0 0 1 1.06 0l4.2 4.2a.75.75 0 0 1 0 1.06ZM12.5 21h8v2h-8z"
              ></path>
            </svg>
          </button>
          <button
            type="button"
            class="secondary editor-icon-button is-danger"
            on:click={cancelEdits}
            disabled={busy || previewBusy}
            aria-label="Cancel edits"
            title="Cancel edits"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M18.3 5.71 12 12l6.3 6.29-1.42 1.42L10.59 13.4 4.29 19.71 2.87 18.3 9.17 12 2.87 5.71 4.29 4.29l6.3 6.3 6.29-6.3z"></path>
            </svg>
          </button>
          <button
            type="button"
            class="secondary editor-icon-button is-accent"
            on:click={breakBone}
            disabled={previewBusy || busy || !currentImageUrl}
            aria-label={previewBusy ? 'Breaking bone' : 'Break bone'}
            title={previewBusy ? 'Breaking bone...' : 'Break bone'}
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="m3 21 7-7 2 2-7 7H3v-2Z"></path>
              <path d="m14.5 3 1.1 2.4L18 6.5l-2.4 1.1L14.5 10l-1.1-2.4L11 6.5l2.4-1.1L14.5 3Z"></path>
              <path d="m20 10 .7 1.5L22 12l-1.3.5L20 14l-.7-1.5L18 12l1.3-.5L20 10Z"></path>
            </svg>
          </button>
          <button
            type="button"
            class="secondary editor-icon-button is-accept"
            on:click={acceptCurrentImage}
            disabled={busy || previewBusy}
            aria-label="Accept image"
            title="Accept image"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M9 16.17 4.83 12 3.41 13.41 9 19 21 7 19.59 5.59z"></path>
            </svg>
          </button>
        </div>

        {#if sizeSliderOpen}
          <div class="editor-size-slider-overlay">
            <span>{tool === 'brush' ? 'Brush size' : 'Eraser size'}</span>
            <input type="range" min="1" max="64" step="1" bind:value={brushSize} />
            <strong>{Math.round(Number(brushSize))} px</strong>
          </div>
        {/if}
      </div>
    {:else}
      <div class="preview-frame">Selected image unavailable</div>
    {/if}
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
    border-radius: 10px;
    overflow: hidden;
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

  .editor-overlay-controls {
    position: absolute;
    top: 0.65rem;
    right: 0.65rem;
    display: grid;
    gap: 0.45rem;
    pointer-events: none;
    z-index: 4;
  }

  .editor-icon-button {
    width: 2.15rem;
    height: 2.15rem;
    border-radius: 999px;
    padding: 0.35rem;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    pointer-events: auto;
    backdrop-filter: blur(2px);
    background: rgba(255, 255, 255, 0.93);
    border: 1px solid rgba(120, 120, 120, 0.35);
  }

  .editor-icon-button svg {
    width: 1.05rem;
    height: 1.05rem;
    fill: currentColor;
  }

  .editor-icon-button.active {
    border-color: var(--accent);
    box-shadow: 0 0 0 2px rgba(14, 124, 123, 0.2);
    color: var(--accent);
  }

  .editor-icon-button.is-danger {
    color: #b23a48;
  }

  .editor-icon-button.is-accent {
    color: #0e7c7b;
  }

  .editor-icon-button.is-accept {
    color: #0f7a35;
  }

  .editor-icon-button:disabled {
    opacity: 0.58;
    cursor: not-allowed;
  }

  .editor-size-slider-overlay {
    position: absolute;
    left: 50%;
    bottom: 0.7rem;
    transform: translateX(-50%);
    display: flex;
    align-items: center;
    gap: 0.55rem;
    padding: 0.45rem 0.7rem;
    border-radius: 999px;
    border: 1px solid rgba(120, 120, 120, 0.35);
    background: rgba(255, 255, 255, 0.95);
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.22);
    backdrop-filter: blur(2px);
    z-index: 4;
    pointer-events: auto;
  }

  .editor-size-slider-overlay span,
  .editor-size-slider-overlay strong {
    font-size: 0.78rem;
    color: #3f454b;
    white-space: nowrap;
  }

  .editor-size-slider-overlay input {
    width: min(220px, 42vw);
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
