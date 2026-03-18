import adapter from '@sveltejs/adapter-node';

/** @type {import('@sveltejs/kit').Config} */
const config = {
  kit: {
    adapter: adapter(),
    outDir: '.svelte-kit-codex',
    alias: {
      $lib: 'src/lib'
    }
  }
};

export default config;
