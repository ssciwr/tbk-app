<script lang="ts">
  import '../app.css';
  import { page } from '$app/stores';
  import { clearToken, getToken } from '$lib/api';
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';

  let loggedIn = false;
  const pipelineStages = [
    { href: '/camera', label: 'Acquire image', stage: 1 },
    { href: '/results', label: 'Review X-Ray', stage: 2 },
    { href: '/fracture', label: 'Apply fractures', stage: 3 },
    { href: '/carousel', label: 'View Results', stage: 4 }
  ];

  onMount(() => {
    loggedIn = Boolean(getToken());
  });

  function logout(): void {
    clearToken();
    loggedIn = false;
    goto('/login');
  }

  function isActive(pathname: string, href: string): boolean {
    return pathname === href || pathname.startsWith(`${href}/`);
  }
</script>

<header class="pipeline-header">
  <div class="pipeline-track">
    {#each pipelineStages as stage, index}
      <a
        href={stage.href}
        class="stage-chip"
        class:active={isActive($page.url.pathname, stage.href)}
        aria-current={isActive($page.url.pathname, stage.href) ? 'page' : undefined}
      >
        <span class="stage-number">Stage {stage.stage}</span>
        <span class="stage-label">{stage.label}</span>
      </a>
      {#if index < pipelineStages.length - 1}
        <span class="stage-arrow" aria-hidden="true">→</span>
      {/if}
    {/each}
  </div>
</header>

<main>
  <slot />
</main>

<footer class="layout-footer">
  <a href="/admin">QR-Code generation</a>
  <a href="/about">About</a>
  {#if loggedIn}
    <button class="secondary" on:click={logout}>Logout</button>
  {/if}
</footer>

<style>
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

  .layout-footer button {
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

    .layout-footer button {
      margin-left: 0;
    }
  }
</style>
