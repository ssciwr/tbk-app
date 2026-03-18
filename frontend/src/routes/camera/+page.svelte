<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import jsQR from 'jsqr';
  import { authedFetch } from '$lib/api';
  import { requireAuthRedirect } from '$lib/auth';

  let childName = '';
  let animalName = '';
  let qrContent = '';

  let captureMessage = '';
  let uploadMessage = '';
  let cameraError = '';

  let videoEl: HTMLVideoElement | null = null;
  let stream: MediaStream | null = null;
  let scanHandle: ReturnType<typeof setInterval> | null = null;
  let scanCanvas: HTMLCanvasElement | null = null;
  let scanStatus = 'Point the camera at a QR code.';
  let scanInFlight = false;

  let capturedFile: File | null = null;
  let previewUrl = '';

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

      // Try to enforce a square stream where supported.
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
      startQrScanner();
    } catch {
      cameraError = 'Could not access webcam; use file upload instead.';
    }
  }

  function stopCamera(): void {
    if (scanHandle) {
      clearInterval(scanHandle);
      scanHandle = null;
    }
    if (stream) {
      for (const track of stream.getTracks()) {
        track.stop();
      }
      stream = null;
    }
  }

  function startQrScanner(): void {
    if (!videoEl) {
      return;
    }

    const BarcodeDetectorCtor = (window as any).BarcodeDetector;
    const detector = BarcodeDetectorCtor
      ? new BarcodeDetectorCtor({ formats: ['qr_code'] })
      : null;
    scanCanvas = document.createElement('canvas');

    scanHandle = setInterval(async () => {
      if (scanInFlight) {
        return;
      }
      scanInFlight = true;
      try {
        const detectedValue = await scanQrFromLiveCamera(detector);
        if (detectedValue) {
          qrContent = detectedValue;
          scanStatus = 'QR code detected.';
        }
      } finally {
        scanInFlight = false;
      }
    }, 700);
  }

  async function scanQrFromLiveCamera(detector?: any): Promise<string | null> {
    if (!videoEl || !scanCanvas || videoEl.readyState < 2) {
      return null;
    }

    scanCanvas.width = videoEl.videoWidth;
    scanCanvas.height = videoEl.videoHeight;
    const context = scanCanvas.getContext('2d');
    if (!context) {
      return null;
    }
    context.drawImage(videoEl, 0, 0);

    if (detector) {
      try {
        const detections = await detector.detect(scanCanvas);
        if (detections.length > 0 && detections[0].rawValue) {
          return detections[0].rawValue;
        }
      } catch {
        // Fallback to jsQR below.
      }
    }

    const imageData = context.getImageData(0, 0, scanCanvas.width, scanCanvas.height);
    const code = jsQR(imageData.data, imageData.width, imageData.height, {
      inversionAttempts: 'attemptBoth'
    });
    return code?.data ?? null;
  }

  async function scanNowFromCamera(): Promise<void> {
    const detectedValue = await scanQrFromLiveCamera((window as any).BarcodeDetector
      ? new (window as any).BarcodeDetector({ formats: ['qr_code'] })
      : null);

    if (detectedValue) {
      qrContent = detectedValue;
      scanStatus = 'QR code detected.';
      return;
    }
    scanStatus = 'No QR code detected. Keep it in frame and try again.';
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

    // Always produce a square image by center-cropping the camera frame.
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

  async function submitCase(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    uploadMessage = '';

    if (!capturedFile) {
      uploadMessage = 'Capture or upload an image first.';
      return;
    }

    const form = new FormData();
    form.append('file', capturedFile);
    form.append('child_name', childName);
    form.append('animal_name', animalName);
    form.append('qr_content', qrContent);

    const response = await authedFetch('/api/cases', {
      method: 'POST',
      body: form
    });

    if (!response.ok) {
      uploadMessage = 'Failed to upload case.';
      return;
    }

    await response.json();
    await goto('/results');
  }

  onMount(async () => {
    const token = await requireAuthRedirect();
    if (!token) {
      return;
    }
    await startCamera();
  });

  onDestroy(() => {
    stopCamera();
    revokePreview();
  });
</script>

<div class="grid cols-2">
  <section class="card">
    <h1>Camera & QR Scan</h1>
    {#if previewUrl}
      <img class="preview captured-frame" src={previewUrl} alt="Captured teddy" />
    {:else}
      <video bind:this={videoEl} autoplay playsinline muted class="preview"></video>
    {/if}
    <div style="display:flex; gap:0.5rem; margin-top:0.8rem; flex-wrap:wrap;">
      <button type="button" on:click={previewUrl ? discardCaptured : captureFromWebcam}>
        {previewUrl ? 'Discard image' : 'Capture'}
      </button>
      {#if !previewUrl}
        <button type="button" class="secondary" on:click={scanNowFromCamera}>Scan QR Now</button>
      {/if}
      <label class="secondary" style="display:inline-block; margin:0; padding:0.45rem 0.7rem; border-radius:8px; border:1px solid var(--border); cursor:pointer;">
        Upload File
        <input type="file" accept="image/*" on:change={onFileChange} style="display:none;" />
      </label>
    </div>
    {#if captureMessage}
      <p>{captureMessage}</p>
    {/if}
    {#if cameraError}
      <p style="color:#b23a48;">{cameraError}</p>
    {/if}
    <p>{scanStatus}</p>
  </section>

  <section class="card">
    <h2>Case Details</h2>
    <form on:submit={submitCase}>
      <label>
        Child name
        <input bind:value={childName} required />
      </label>

      <label>
        Animal name
        <input bind:value={animalName} required />
      </label>

      <label>
        QR content
        <input bind:value={qrContent} required placeholder="Auto-filled when QR is detected" />
      </label>

      <button type="submit">Upload Case</button>
    </form>

    {#if uploadMessage}
      <p>{uploadMessage}</p>
    {/if}
  </section>
</div>

<style>
  video.preview {
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

  img.captured-frame {
    display: block;
    width: 100%;
    max-width: 100%;
    aspect-ratio: 1 / 1;
    object-fit: cover;
  }
</style>
