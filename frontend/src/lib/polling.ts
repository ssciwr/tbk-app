export type AsyncPoller = {
  start: (immediate?: boolean) => void;
  stop: () => void;
};

type PollerOptions = {
  intervalMs: number;
  maxIntervalMs?: number;
  backoffFactor?: number;
  pauseWhenHidden?: boolean;
};

export function createAsyncPoller(
  task: (signal: AbortSignal) => Promise<void>,
  options: PollerOptions
): AsyncPoller {
  const maxIntervalMs = options.maxIntervalMs ?? options.intervalMs;
  const backoffFactor = options.backoffFactor ?? 2;
  let stopped = true;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let activeController: AbortController | null = null;
  let consecutiveFailures = 0;

  function clearTimer(): void {
    if (timer) {
      clearTimeout(timer);
      timer = null;
    }
  }

  function nextDelay(): number {
    if (consecutiveFailures === 0) {
      return options.intervalMs;
    }
    return Math.min(
      maxIntervalMs,
      Math.round(options.intervalMs * Math.pow(backoffFactor, consecutiveFailures))
    );
  }

  function schedule(delay = nextDelay()): void {
    if (stopped) {
      return;
    }
    clearTimer();
    timer = setTimeout(() => {
      void run();
    }, delay);
  }

  async function run(): Promise<void> {
    if (stopped) {
      return;
    }
    if (options.pauseWhenHidden && typeof document !== 'undefined' && document.hidden) {
      schedule(options.intervalMs);
      return;
    }

    const controller = new AbortController();
    activeController = controller;
    try {
      await task(controller.signal);
      consecutiveFailures = 0;
    } catch (error) {
      if (!controller.signal.aborted) {
        consecutiveFailures += 1;
        console.warn('Polling request failed', error);
      }
    } finally {
      if (activeController === controller) {
        activeController = null;
      }
      schedule();
    }
  }

  return {
    start(immediate = true): void {
      if (!stopped) {
        return;
      }
      stopped = false;
      consecutiveFailures = 0;
      if (immediate) {
        void run();
      } else {
        schedule(options.intervalMs);
      }
    },
    stop(): void {
      stopped = true;
      clearTimer();
      if (activeController) {
        activeController.abort();
        activeController = null;
      }
    }
  };
}
