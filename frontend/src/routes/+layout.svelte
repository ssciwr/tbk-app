<script lang="ts">
  import '../app.css';
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { authToken, clearToken, loadAppConfig } from '$lib/api';
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

  $: pipelineStages = basePipelineStages.map((stage) => ({
    ...stage,
    enabled: stage.key === 'fracture' ? fractureStageEnabled : true
  }));

  onMount(() => {
    void syncAppConfig(true);
  });

  $: if ($authToken) {
    void syncAppConfig();
  }

  $: isCarouselShowcase =
    $page.url.pathname === '/carousel' || $page.url.pathname.startsWith('/carousel/');
</script>

<div class="app-shell">
  {#if !isCarouselShowcase}
    <header class="pipeline-header">
      <div class="pipeline-track">
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
    </header>
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

  @media (max-width: 900px) {
    .pipeline-track {
      justify-content: flex-start;
    }

    .stage-arrow {
      display: none;
    }

    .stage-chip {
      width: 100%;
    }

    .layout-footer .logout-link {
      margin-left: 0;
    }
  }
</style>
