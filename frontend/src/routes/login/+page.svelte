<script lang="ts">
  import { goto } from '$app/navigation';
  import { apiUrl, setToken } from '$lib/api';

  let password = '';
  let error = '';
  let loading = false;

  async function login(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    loading = true;
    error = '';

    const body = new URLSearchParams();
    body.set('password', password);

    const response = await fetch(apiUrl('/api/auth/token'), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded'
      },
      body
    });

    if (!response.ok) {
      error = 'Login failed. Check password.';
      loading = false;
      return;
    }

    const data = await response.json();
    setToken(data.access_token);
    goto('/camera');
  }
</script>

<div class="card" style="max-width: 420px; margin: 2rem auto;">
  <h1>Login</h1>
  <p>Use the shared event password.</p>

  <form on:submit={login}>
    <label>
      Password
      <input type="password" bind:value={password} required />
    </label>
    <button type="submit" disabled={loading}>{loading ? 'Logging in...' : 'Login'}</button>
  </form>

  {#if error}
    <p style="color:#b23a48;">{error}</p>
  {/if}
</div>
