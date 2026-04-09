<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import jsQR from 'jsqr';
  import { authedFetch } from '$lib/api';
  import { rememberProfiledCamera, startProfiledCamera, switchProfiledCamera } from '$lib/camera';
  import { requireAuthRedirect } from '$lib/auth';

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
        Animal type (optional)
        <input bind:value={animalType} placeholder="e.g. bear, rabbit, fox" />
      </label>

      <label>
        QR content
        <input bind:value={qrContent} required placeholder="Auto-filled when QR is detected" />
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
</style>
