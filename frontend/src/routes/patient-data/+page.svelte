<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { authedFetch } from '$lib/api';
  import { rememberProfiledCamera, startProfiledCamera, switchProfiledCamera } from '$lib/camera';
  import { requireAuthRedirect } from '$lib/auth';

  const SCAN_INTERVAL_MS = 350;
  const WORKER_FALLBACK_EVERY = 3;
  const FULL_FRAME_FALLBACK_EVERY = 4;
  const CENTER_SCAN_RATIO = 0.72;
  const MAX_SCAN_DIMENSION = 420;

  type ScanRegion = {
    sx: number;
    sy: number;
    sw: number;
    sh: number;
  };

  type WorkerScanResponse = {
    id: number;
    qrContent: string | null;
    error?: string;
  };

  let childName = '';
  let animalName = '';
  let animalType = '';
  let qrContent = '';

  let submitMessage = '';
  let submitting = false;
  let cameraError = '';
  let switchingCamera = false;

  let videoEl: HTMLVideoElement | null = null;
  let stream: MediaStream | null = null;
  let scanHandle: ReturnType<typeof setTimeout> | null = null;
  let scanCanvas: HTMLCanvasElement | null = null;
  let scanContext: CanvasRenderingContext2D | null = null;
  let scanStatus = 'Point the camera at a QR code.';
  let scanInFlight = false;
  let scanAttempt = 0;
  let scanDetected = false;
  let scanPausedForManualEntry = false;
  let scanPausedForHiddenTab = false;
  let scanSessionId = 0;
  let barcodeDetector: any | null = null;
  let qrWorker: Worker | null = null;
  let workerRequestId = 0;
  const pendingWorkerScans = new Map<
    number,
    {
      resolve: (value: string | null) => void;
      reject: (reason?: unknown) => void;
    }
  >();

  async function startCamera(): Promise<void> {
    cameraError = '';
    if (!navigator.mediaDevices?.getUserMedia) {
      cameraError = 'Webcam API not available; enter QR content manually.';
      return;
    }

    try {
      stream = await startProfiledCamera('patient-data', videoEl);
      startQrScanner();
    } catch {
      cameraError = 'Could not access webcam; enter QR content manually.';
    }
  }

  function stopCamera(): void {
    destroyQrScanner();
    if (stream) {
      rememberProfiledCamera('patient-data', stream);
      for (const track of stream.getTracks()) {
        track.stop();
      }
      stream = null;
    }
  }

  function advanceScanSession(): number {
    scanSessionId += 1;
    return scanSessionId;
  }

  function stopScanLoop(): void {
    if (scanHandle) {
      clearTimeout(scanHandle);
      scanHandle = null;
    }
  }

  function rejectPendingWorkerScans(reason: string): void {
    for (const { reject } of pendingWorkerScans.values()) {
      reject(new Error(reason));
    }
    pendingWorkerScans.clear();
  }

  function destroyQrWorker(): void {
    rejectPendingWorkerScans('QR worker stopped');
    if (qrWorker) {
      qrWorker.terminate();
      qrWorker = null;
    }
  }

  function destroyQrScanner(): void {
    stopScanLoop();
    advanceScanSession();
    scanInFlight = false;
    scanAttempt = 0;
    barcodeDetector = null;
    scanCanvas = null;
    scanContext = null;
    destroyQrWorker();
  }

  function canScan(): boolean {
    return Boolean(
      stream &&
        videoEl &&
        scanCanvas &&
        scanContext &&
        !scanDetected &&
        !scanPausedForManualEntry &&
        !scanPausedForHiddenTab
    );
  }

  function scheduleNextScan(delay = SCAN_INTERVAL_MS): void {
    stopScanLoop();
    if (!canScan()) {
      return;
    }
    const sessionId = scanSessionId;
    scanHandle = setTimeout(() => {
      void performScheduledScan(sessionId);
    }, delay);
  }

  function ensureScanCanvasSize(width: number, height: number): boolean {
    if (!scanCanvas || !scanContext) {
      return false;
    }
    if (scanCanvas.width !== width) {
      scanCanvas.width = width;
    }
    if (scanCanvas.height !== height) {
      scanCanvas.height = height;
    }
    return true;
  }

  function createCenteredScanRegion(videoWidth: number, videoHeight: number): ScanRegion {
    const size = Math.max(1, Math.floor(Math.min(videoWidth, videoHeight) * CENTER_SCAN_RATIO));
    return {
      sx: Math.max(0, Math.floor((videoWidth - size) / 2)),
      sy: Math.max(0, Math.floor((videoHeight - size) / 2)),
      sw: size,
      sh: size
    };
  }

  function buildScanRegions(videoWidth: number, videoHeight: number): ScanRegion[] {
    const regions = [createCenteredScanRegion(videoWidth, videoHeight)];
    if (scanAttempt % FULL_FRAME_FALLBACK_EVERY !== 0) {
      return regions;
    }

    const fullFrame = { sx: 0, sy: 0, sw: videoWidth, sh: videoHeight };
    if (regions[0].sw === fullFrame.sw && regions[0].sh === fullFrame.sh) {
      return regions;
    }

    return [...regions, fullFrame];
  }

  function getDecodeCanvasDimensions(region: ScanRegion): { width: number; height: number } {
    const scale = Math.min(1, MAX_SCAN_DIMENSION / Math.max(region.sw, region.sh));
    return {
      width: Math.max(1, Math.round(region.sw * scale)),
      height: Math.max(1, Math.round(region.sh * scale))
    };
  }

  function drawScanRegion(region: ScanRegion): boolean {
    if (!videoEl || !scanCanvas || !scanContext) {
      return false;
    }
    const { width, height } = getDecodeCanvasDimensions(region);
    if (!ensureScanCanvasSize(width, height)) {
      return false;
    }

    scanContext.drawImage(videoEl, region.sx, region.sy, region.sw, region.sh, 0, 0, width, height);
    return true;
  }

  async function detectWithBarcodeDetector(): Promise<string | null> {
    if (!barcodeDetector || !scanCanvas) {
      return null;
    }

    try {
      const detections = await barcodeDetector.detect(scanCanvas);
      return detections[0]?.rawValue ?? null;
    } catch {
      barcodeDetector = null;
      return null;
    }
  }

  function ensureQrWorker(): Worker | null {
    if (qrWorker || typeof Worker === 'undefined') {
      return qrWorker;
    }

    qrWorker = new Worker(new URL('../../lib/workers/qr-scanner.worker.ts', import.meta.url), {
      type: 'module'
    });
    qrWorker.onmessage = (event: MessageEvent<WorkerScanResponse>) => {
      const pending = pendingWorkerScans.get(event.data.id);
      if (!pending) {
        return;
      }
      pendingWorkerScans.delete(event.data.id);
      if (event.data.error) {
        pending.reject(new Error(event.data.error));
        return;
      }
      pending.resolve(event.data.qrContent);
    };
    qrWorker.onerror = () => {
      rejectPendingWorkerScans('QR worker failed');
      qrWorker?.terminate();
      qrWorker = null;
    };

    return qrWorker;
  }

  async function detectWithWorker(): Promise<string | null> {
    if (!scanCanvas || !scanContext) {
      return null;
    }

    const worker = ensureQrWorker();
    if (!worker) {
      return null;
    }

    const imageData = scanContext.getImageData(0, 0, scanCanvas.width, scanCanvas.height);
    const requestId = ++workerRequestId;

    return await new Promise<string | null>((resolve, reject) => {
      pendingWorkerScans.set(requestId, { resolve, reject });
      worker.postMessage(
        {
          id: requestId,
          width: imageData.width,
          height: imageData.height,
          data: imageData.data.buffer
        },
        [imageData.data.buffer]
      );
    });
  }

  function markQrDetected(detectedValue: string): void {
    qrContent = detectedValue;
    scanDetected = true;
    scanPausedForManualEntry = false;
    scanPausedForHiddenTab = false;
    scanStatus = 'QR code detected.';
    stopScanLoop();
    advanceScanSession();
  }

  function pauseScannerForManualEntry(): void {
    scanDetected = false;
    scanPausedForManualEntry = true;
    scanStatus = 'QR scanning paused while editing manually.';
    stopScanLoop();
    advanceScanSession();
  }

  function resumeQrScanner(): void {
    if (!stream || !videoEl || !scanCanvas || !scanContext) {
      return;
    }

    scanDetected = false;
    scanPausedForManualEntry = false;
    scanPausedForHiddenTab = typeof document !== 'undefined' ? document.hidden : false;
    scanAttempt = 0;
    scanStatus = scanPausedForHiddenTab ? 'QR scanning paused while the tab is hidden.' : 'Point the camera at a QR code.';
    advanceScanSession();
    if (!scanPausedForHiddenTab) {
      scheduleNextScan(0);
    }
  }

  function handleVisibilityChange(): void {
    scanPausedForHiddenTab = document.hidden;

    if (scanPausedForHiddenTab) {
      stopScanLoop();
      advanceScanSession();
      if (!scanDetected && !scanPausedForManualEntry) {
        scanStatus = 'QR scanning paused while the tab is hidden.';
      }
      return;
    }

    if (scanDetected || scanPausedForManualEntry || !scanCanvas || !scanContext) {
      return;
    }

    scanAttempt = 0;
    scanStatus = 'Point the camera at a QR code.';
    advanceScanSession();
    scheduleNextScan(0);
  }

  async function switchCamera(): Promise<void> {
    if (switchingCamera || !stream) {
      return;
    }

    cameraError = '';
    switchingCamera = true;
    const currentStream = stream;

    try {
      const nextStream = await switchProfiledCamera('patient-data', currentStream, videoEl);
      stream = nextStream;
      for (const track of currentStream.getTracks()) {
        track.stop();
      }
    } catch {
      cameraError = 'No alternative camera available for this browser session.';
    } finally {
      switchingCamera = false;
    }
  }

  function startQrScanner(): void {
    if (!videoEl) {
      return;
    }

    scanCanvas = document.createElement('canvas');
    scanContext = scanCanvas.getContext('2d', { willReadFrequently: true });
    const BarcodeDetectorCtor = (window as any).BarcodeDetector;
    barcodeDetector = BarcodeDetectorCtor ? new BarcodeDetectorCtor({ formats: ['qr_code'] }) : null;
    scanAttempt = 0;
    scanPausedForHiddenTab = typeof document !== 'undefined' ? document.hidden : false;
    scanStatus = scanPausedForHiddenTab ? 'QR scanning paused while the tab is hidden.' : 'Point the camera at a QR code.';
    advanceScanSession();
    if (!scanPausedForHiddenTab) {
      scheduleNextScan(0);
    }
  }

  async function scanQrFromLiveCamera(sessionId: number): Promise<string | null> {
    if (!videoEl || !scanCanvas || !scanContext || videoEl.readyState < 2) {
      return null;
    }

    const videoWidth = videoEl.videoWidth;
    const videoHeight = videoEl.videoHeight;
    if (!videoWidth || !videoHeight) {
      return null;
    }

    scanAttempt += 1;
    const shouldUseWorkerFallback = !barcodeDetector || scanAttempt % WORKER_FALLBACK_EVERY === 0;

    for (const region of buildScanRegions(videoWidth, videoHeight)) {
      if (!drawScanRegion(region)) {
        continue;
      }

      if (barcodeDetector) {
        const barcodeValue = await detectWithBarcodeDetector();
        if (barcodeValue) {
          return barcodeValue;
        }
      }

      if (sessionId !== scanSessionId || !canScan()) {
        return null;
      }

      if (!shouldUseWorkerFallback) {
        continue;
      }

      const workerValue = await detectWithWorker();
      if (workerValue) {
        return workerValue;
      }

      if (sessionId !== scanSessionId || !canScan()) {
        return null;
      }
    }

    return null;
  }

  async function performScheduledScan(sessionId: number): Promise<void> {
    if (scanInFlight || sessionId !== scanSessionId || !canScan()) {
      return;
    }

    scanInFlight = true;
    let shouldScheduleNext = false;

    try {
      const detectedValue = await scanQrFromLiveCamera(sessionId);
      if (sessionId !== scanSessionId || !canScan()) {
        return;
      }

      if (detectedValue) {
        markQrDetected(detectedValue);
        return;
      }

      shouldScheduleNext = true;
    } catch {
      if (sessionId === scanSessionId && canScan()) {
        shouldScheduleNext = true;
      }
    } finally {
      scanInFlight = false;
      if (shouldScheduleNext) {
        scheduleNextScan();
      }
    }
  }

  function handleQrContentInput(): void {
    pauseScannerForManualEntry();
  }

  async function submitCaseMetadata(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    if (submitting) {
      return;
    }

    submitMessage = '';
    submitting = true;

    try {
      const form = new FormData();
      form.append('child_name', childName);
      form.append('animal_name', animalName);
      form.append('animal_type', animalType);
      form.append('qr_content', qrContent);

      const response = await authedFetch('/api/cases', {
        method: 'POST',
        body: form
      });

      if (!response.ok) {
        submitMessage = 'Failed to create case metadata.';
        return;
      }

      await response.json();
      await goto('/camera');
    } catch {
      submitMessage = 'Failed to create case metadata.';
    } finally {
      submitting = false;
    }
  }

  onMount(async () => {
    document.addEventListener('visibilitychange', handleVisibilityChange);
    const token = await requireAuthRedirect();
    if (!token) {
      return;
    }
    await startCamera();
  });

  onDestroy(() => {
    document.removeEventListener('visibilitychange', handleVisibilityChange);
    stopCamera();
  });
</script>

<div class="grid cols-2">
  <section class="card">
    <h1>Patient Data & QR Scan</h1>
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
      <button
        type="button"
        class="secondary preview-corner-button switch-camera-overlay-button"
        on:click={switchCamera}
        disabled={!stream || switchingCamera}
        aria-label={switchingCamera ? 'Switching camera' : 'Switch camera'}
        title={switchingCamera ? 'Switching camera...' : 'Switch camera'}
      >
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path
            d="M12 12c1.66 0 3-1.34 3-3s-1.34-3-3-3-3 1.34-3 3 1.34 3 3 3zm9-7h-3.17l-1.84-2H8.01L6.17 5H3c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h18c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 14H3V7h4.05l1.83-2h6.24l1.83 2H21v12z"
          ></path>
        </svg>
      </button>
    </div>
    {#if cameraError}
      <p style="color:#b23a48;">{cameraError}</p>
    {/if}
    <div class="scan-status-row">
      <p>{scanStatus}</p>
      {#if stream && (scanDetected || scanPausedForManualEntry)}
        <button type="button" class="secondary" on:click={resumeQrScanner}>
          {scanDetected ? 'Scan Again' : 'Resume Scanning'}
        </button>
      {/if}
    </div>
  </section>

  <section class="card">
    <h2>Case Details</h2>
    <p class="form-note">
      For fast-track intake, you can leave the child and animal names blank and save only the QR code.
      Nameless cases skip watermarking on generated images.
    </p>
    <form on:submit={submitCaseMetadata}>
      <label>
        Child name
        <input bind:value={childName} placeholder="Optional for fast-track" />
      </label>

      <label>
        Animal name
        <input bind:value={animalName} placeholder="Optional for fast-track" />
      </label>

      <label>
        Animal type (optional)
        <input bind:value={animalType} placeholder="e.g. bear, rabbit, fox" />
      </label>

      <label>
        QR content
        <input
          bind:value={qrContent}
          required
          placeholder="Auto-filled when QR is detected"
          on:input={handleQrContentInput}
        />
      </label>

      <button type="submit" disabled={submitting}>
        {submitting ? 'Saving patient data...' : 'Save Patient Data'}
      </button>
    </form>

    {#if submitMessage}
      <p>{submitMessage}</p>
    {/if}
  </section>
</div>

<style>
  .camera-feed {
    position: relative;
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

  .preview-corner-button svg {
    width: 1rem;
    height: 1rem;
    fill: currentColor;
  }

  .switch-camera-overlay-button {
    pointer-events: auto;
  }

  .switch-camera-overlay-button:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .scan-status-row {
    display: flex;
    gap: 0.75rem;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
  }

  .scan-status-row p {
    margin: 0;
  }

  .form-note {
    margin-top: 0;
  }
</style>
