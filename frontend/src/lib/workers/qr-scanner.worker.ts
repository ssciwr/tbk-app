/// <reference lib="webworker" />

import jsQR from 'jsqr';

type WorkerScanRequest = {
  id: number;
  width: number;
  height: number;
  data: ArrayBuffer;
};

type WorkerScanResponse = {
  id: number;
  qrContent: string | null;
  error?: string;
};

const workerScope: DedicatedWorkerGlobalScope = self as DedicatedWorkerGlobalScope;

workerScope.onmessage = (event: MessageEvent<WorkerScanRequest>) => {
  const { id, width, height, data } = event.data;

  try {
    const pixels = new Uint8ClampedArray(data);
    const code = jsQR(pixels, width, height, {
      inversionAttempts: 'attemptBoth'
    });

    const response: WorkerScanResponse = {
      id,
      qrContent: code?.data ?? null
    };
    workerScope.postMessage(response);
  } catch (error) {
    const response: WorkerScanResponse = {
      id,
      qrContent: null,
      error: error instanceof Error ? error.message : 'QR scan failed'
    };
    workerScope.postMessage(response);
  }
};

export {};
