<script lang="ts">
  import '../app.css';
  import { onDestroy, onMount } from 'svelte';
  import { page } from '$app/stores';
  import { authToken, clearToken, loadAppConfig, loadRunnerStatus } from '$lib/api';
  import { goto } from '$app/navigation';

  type StageKey = 'patient-data' | 'camera' | 'review' | 'fracture' | 'results';
  type PipelineStage = {
    key: StageKey;
    href: string;
    label: string;
    stage: number;
    enabled: boolean;
  };

  const basePipelineStages: Array<Omit<PipelineStage, 'enabled'>> = [
    { key: 'patient-data', href: '/patient-data', label: 'Patient data', stage: 1 },
    { key: 'camera', href: '/camera', label: 'Acquire image', stage: 2 },
    { key: 'review', href: '/review', label: 'Review X-Ray', stage: 3 },
    { key: 'fracture', href: '/fracture', label: 'Apply fractures', stage: 4 },
    { key: 'results', href: '/results', label: 'View Results', stage: 5 }
  ];
  const RUNNER_STATUS_POLL_MS = 5000;

  function logout(): void {
    clearToken();
    goto('/login');
  }

  function isActive(pathname: string, href: string): boolean {
    return pathname === href || pathname.startsWith(`${href}/`);
  }

  let isCarouselShowcase = false;
  let fractureStageEnabled = true;
  let configLoadingForToken: string | null = null;
  let pipelineStages: PipelineStage[] = [];
  let runnerConnected: boolean | null = null;
  let runnerStatusPollHandle: ReturnType<typeof setInterval> | null = null;
  let runnerStatusToken: string | null = null;

  async function syncAppConfig(force = false): Promise<void> {
    if (!$authToken) {
      fractureStageEnabled = true;
      return;
    }

    if (configLoadingForToken === $authToken && !force) {
      return;
    }

    configLoadingForToken = $authToken;
    const config = await loadAppConfig(force);
    fractureStageEnabled = config.fracture_editor_enabled;
  }

  async function refreshRunnerStatus(): Promise<void> {
    if (!$authToken) {
      runnerConnected = null;
      return;
    }

    const status = await loadRunnerStatus();
    if (!status) {
      return;
    }
    runnerConnected = status.runner_connected;
  }

  function stopRunnerStatusPolling(): void {
    if (runnerStatusPollHandle) {
      clearInterval(runnerStatusPollHandle);
      runnerStatusPollHandle = null;
    }
  }

  function startRunnerStatusPolling(): void {
    stopRunnerStatusPolling();
    void refreshRunnerStatus();
    runnerStatusPollHandle = setInterval(() => {
      void refreshRunnerStatus();
    }, RUNNER_STATUS_POLL_MS);
  }

  $: pipelineStages = basePipelineStages.map((stage) => ({
    ...stage,
    enabled: stage.key === 'fracture' ? fractureStageEnabled : true
  }));

  onMount(() => {
    void syncAppConfig(true);
  });

  onDestroy(() => {
    stopRunnerStatusPolling();
  });

  $: if ($authToken) {
    void syncAppConfig();
  }

  $: if ($authToken !== runnerStatusToken) {
    runnerStatusToken = $authToken;
    if (!$authToken) {
      runnerConnected = null;
      stopRunnerStatusPolling();
    } else {
      startRunnerStatusPolling();
    }
  }

  $: isCarouselShowcase =
    $page.url.pathname === '/carousel' || $page.url.pathname.startsWith('/carousel/');
</script>

<div class="app-shell">
  {#if !isCarouselShowcase}
    <header class="pipeline-header">
      <div class="pipeline-track pipeline-track-desktop">
        {#each pipelineStages as stage, index}
          {#if stage.enabled}
            <a
              href={stage.href}
              class="stage-chip"
              class:active={isActive($page.url.pathname, stage.href)}
              aria-current={isActive($page.url.pathname, stage.href) ? 'page' : undefined}
            >
              <span class="stage-number">Stage {stage.stage}</span>
              <span class="stage-label">{stage.label}</span>
            </a>
          {:else}
            <span class="stage-chip disabled" aria-disabled="true">
              <span class="stage-number">Stage {stage.stage}</span>
              <span class="stage-label">{stage.label}</span>
            </span>
          {/if}
          {#if index < pipelineStages.length - 1}
            <span class="stage-arrow" aria-hidden="true">→</span>
          {/if}
        {/each}
      </div>
      <div class="pipeline-track-mobile" aria-label="Pipeline stages">
        {#each pipelineStages as stage, index}
          {@const active = isActive($page.url.pathname, stage.href)}
          {#if stage.enabled}
            <a
              href={stage.href}
              class="stage-icon-chip"
              class:active={active}
              aria-current={active ? 'page' : undefined}
              title={`Stage ${stage.stage}: ${stage.label}`}
              aria-label={`Stage ${stage.stage}: ${stage.label}`}
            >
              <span class="stage-icon-glyph" aria-hidden="true">
                {#if stage.key === 'patient-data'}
                  <svg viewBox="0 0 24 24">
                    <circle cx="12" cy="8" r="3"></circle>
                    <path d="M6.5 19c0-3.3 2.5-6 5.5-6s5.5 2.7 5.5 6"></path>
                  </svg>
                {:else if stage.key === 'camera'}
                  <svg viewBox="0 0 24 24">
                    <rect x="4" y="7" width="16" height="12" rx="2"></rect>
                    <path d="M9 7l1.3-2h3.4L15 7"></path>
                    <circle cx="12" cy="13" r="3"></circle>
                  </svg>
                {:else if stage.key === 'review'}
                  <svg viewBox="0 0 24 24">
                    <circle cx="11" cy="11" r="5.5"></circle>
                    <path d="m16 16 4 4"></path>
                  </svg>
                {:else if stage.key === 'fracture'}
                  <svg viewBox="0 0 24 24">
                    <path d="M4 20h4l10-10-4-4L4 16v4z"></path>
                    <path d="m13 7 4 4"></path>
                  </svg>
                {:else}
                  <svg viewBox="0 0 24 24">
                    <circle cx="12" cy="12" r="8"></circle>
                    <path d="m8.5 12.5 2.5 2.5 4.5-5"></path>
                  </svg>
                {/if}
              </span>
            </a>
          {:else}
            <span
              class="stage-icon-chip disabled"
              class:active={active}
              aria-disabled="true"
              title={`Stage ${stage.stage}: ${stage.label} (disabled)`}
              aria-label={`Stage ${stage.stage}: ${stage.label} (disabled)`}
            >
              <span class="stage-icon-glyph" aria-hidden="true">
                {#if stage.key === 'patient-data'}
                  <svg viewBox="0 0 24 24">
                    <circle cx="12" cy="8" r="3"></circle>
                    <path d="M6.5 19c0-3.3 2.5-6 5.5-6s5.5 2.7 5.5 6"></path>
                  </svg>
                {:else if stage.key === 'camera'}
                  <svg viewBox="0 0 24 24">
                    <rect x="4" y="7" width="16" height="12" rx="2"></rect>
                    <path d="M9 7l1.3-2h3.4L15 7"></path>
                    <circle cx="12" cy="13" r="3"></circle>
                  </svg>
                {:else if stage.key === 'review'}
                  <svg viewBox="0 0 24 24">
                    <circle cx="11" cy="11" r="5.5"></circle>
                    <path d="m16 16 4 4"></path>
                  </svg>
                {:else if stage.key === 'fracture'}
                  <svg viewBox="0 0 24 24">
                    <path d="M4 20h4l10-10-4-4L4 16v4z"></path>
                    <path d="m13 7 4 4"></path>
                  </svg>
                {:else}
                  <svg viewBox="0 0 24 24">
                    <circle cx="12" cy="12" r="8"></circle>
                    <path d="m8.5 12.5 2.5 2.5 4.5-5"></path>
                  </svg>
                {/if}
              </span>
            </span>
          {/if}
          {#if index < pipelineStages.length - 1}
            <span class="stage-icon-arrow" aria-hidden="true">→</span>
          {/if}
        {/each}
      </div>
    </header>
  {/if}

  {#if $authToken && runnerConnected === false}
    <div class="runner-warning" role="alert">
      No runner is currently connected. Image generation does not work right now.
    </div>
  {/if}

  <main class="app-main" class:showcase-main={isCarouselShowcase}>
    <slot />
  </main>

  <footer class="layout-footer">
    {#if isCarouselShowcase}
      <a href="/patient-data">X-Ray Pipeline</a>
    {:else}
      <a href="/carousel">Carousel</a>
    {/if}
    <a href="/admin">QR-Code generation</a>
    <a href="/about">About</a>
    {#if $authToken}
      <a class="logout-link" href="/login" on:click|preventDefault={logout}>Logout</a>
    {/if}
  </footer>
</div>

<style>
  .app-shell {
    min-height: 100vh;
    display: flex;
    flex-direction: column;
  }

  .app-main {
    flex: 1;
  }

  .app-main.showcase-main {
    max-width: none;
    width: 100%;
    margin: 0;
  }

  .pipeline-header {
    padding: 0.8rem 1rem;
    border-bottom: 1px solid var(--border);
    background: rgba(255, 255, 255, 0.84);
    backdrop-filter: blur(6px);
  }

  .pipeline-track {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0.5rem;
    flex-wrap: wrap;
  }

  .pipeline-track-mobile {
    display: none;
    align-items: center;
    justify-content: center;
    gap: 0.35rem;
  }

  .stage-chip {
    min-width: 140px;
    border: 1px solid var(--border);
    border-radius: 10px;
    background: #ffffff;
    box-shadow: 0 4px 14px rgba(33, 46, 48, 0.07);
    padding: 0.45rem 0.7rem;
    text-decoration: none;
    color: var(--text);
    display: grid;
    gap: 0.1rem;
  }

  .stage-chip:hover {
    text-decoration: none;
    border-color: #9ab4b5;
  }

  .stage-chip.active {
    border-color: var(--accent);
    box-shadow: 0 0 0 2px rgba(14, 124, 123, 0.18);
    background: #f4fbfb;
  }

  .stage-chip.disabled {
    opacity: 0.5;
    background: #f1f3f4;
    border-style: dashed;
    box-shadow: none;
    color: #5f676f;
  }

  .stage-number {
    font-size: 0.72rem;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: #4a5a63;
  }

  .stage-label {
    font-size: 1rem;
    font-weight: 700;
  }

  .stage-arrow {
    color: #56757a;
    font-size: 1.3rem;
    line-height: 1;
    user-select: none;
  }

  .stage-icon-chip {
    width: 2.35rem;
    height: 2.35rem;
    border: 1px solid var(--border);
    border-radius: 999px;
    background: #ffffff;
    box-shadow: 0 4px 14px rgba(33, 46, 48, 0.07);
    color: #445860;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    text-decoration: none;
  }

  .stage-icon-chip:hover {
    text-decoration: none;
    border-color: #9ab4b5;
  }

  .stage-icon-chip.active {
    border-color: var(--accent);
    box-shadow: 0 0 0 2px rgba(14, 124, 123, 0.18);
    background: #f4fbfb;
    color: var(--accent);
  }

  .stage-icon-chip.disabled {
    opacity: 0.5;
    background: #f1f3f4;
    border-style: dashed;
    box-shadow: none;
    color: #5f676f;
  }

  .stage-icon-glyph {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 1.2rem;
    height: 1.2rem;
  }

  .stage-icon-glyph svg {
    width: 100%;
    height: 100%;
    stroke: currentColor;
    fill: none;
    stroke-width: 1.8;
    stroke-linecap: round;
    stroke-linejoin: round;
  }

  .stage-icon-arrow {
    color: #5f7377;
    font-size: 0.85rem;
    line-height: 1;
    user-select: none;
  }

  .layout-footer {
    max-width: 1100px;
    margin: 0 auto;
    padding: 0 1rem 1rem;
    display: flex;
    align-items: center;
    gap: 0.8rem;
    flex-wrap: wrap;
  }

  .layout-footer a {
    color: var(--accent);
  }

  .layout-footer .logout-link {
    margin-left: auto;
  }

  .runner-warning {
    max-width: 1100px;
    margin: 0.9rem auto 0;
    padding: 0.7rem 0.9rem;
    border: 1px solid #d18f00;
    border-radius: 10px;
    background: #fff4d8;
    color: #5c3d00;
    font-weight: 600;
  }

  @media (max-width: 900px) {
    .pipeline-track-desktop {
      display: none;
    }

    .pipeline-track-mobile {
      display: flex;
      justify-content: center;
      flex-wrap: nowrap;
    }

    .layout-footer .logout-link {
      margin-left: 0;
    }

    .runner-warning {
      margin: 0.75rem 1rem 0;
    }
  }
</style>
