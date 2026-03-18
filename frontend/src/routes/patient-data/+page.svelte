<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import jsQR from 'jsqr';
  import { authedFetch } from '$lib/api';
  import { rememberProfiledCamera, startProfiledCamera } from '$lib/camera';
  import { requireAuthRedirect } from '$lib/auth';

  let childName = '';
  let animalName = '';
  let qrContent = '';

  let submitMessage = '';
  let cameraError = '';

  let videoEl: HTMLVideoElement | null = null;
  let stream: MediaStream | null = null;
  let scanHandle: ReturnType<typeof setInterval> | null = null;
  let scanCanvas: HTMLCanvasElement | null = null;
  let scanStatus = 'Point the camera at a QR code.';
  let scanInFlight = false;

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
    if (scanHandle) {
      clearInterval(scanHandle);
      scanHandle = null;
    }
    if (stream) {
      rememberProfiledCamera('patient-data', stream);
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

  async function submitCaseMetadata(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    submitMessage = '';

    const form = new FormData();
    form.append('child_name', childName);
    form.append('animal_name', animalName);
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
    </div>
    {#if cameraError}
      <p style="color:#b23a48;">{cameraError}</p>
    {/if}
    <p>{scanStatus}</p>
  </section>

  <section class="card">
    <h2>Case Details</h2>
    <form on:submit={submitCaseMetadata}>
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

      <button type="submit">Save Patient Data</button>
    </form>

    {#if submitMessage}
      <p>{submitMessage}</p>
    {/if}
  </section>
</div>

<style>
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
</style>
