<script lang="ts">
  import { onMount } from 'svelte';
  import { requireAuthRedirect } from '$lib/auth';

  onMount(async () => {
    await requireAuthRedirect();
  });
</script>

<div class="card">
  <h1>Teddy Hospital X-Ray</h1>
  <p>This dashboard coordinates image capture, AI result review, and the X-Ray carousel.</p>
</div>
