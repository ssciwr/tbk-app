<script lang="ts">
  import '../app.css';
  import { clearToken, getToken } from '$lib/api';
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';

  let loggedIn = false;

  onMount(() => {
    loggedIn = Boolean(getToken());
  });

  function logout(): void {
    clearToken();
    loggedIn = false;
    goto('/login');
  }
</script>

<nav>
  <a href="/">Home</a>
  <a href="/admin">Admin</a>
  <a href="/camera">Camera</a>
  <a href="/results">Results</a>
  <a href="/carousel">Carousel</a>
  <a href="/about">About</a>
  {#if loggedIn}
    <button class="secondary" on:click={logout}>Logout</button>
  {/if}
</nav>

<main>
  <slot />
</main>
