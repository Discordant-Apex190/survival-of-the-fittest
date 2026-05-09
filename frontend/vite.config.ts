import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [sveltekit()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/pixi.js')) return 'pixi-engine';
          if (id.includes('node_modules/matter-js')) return 'physics-engine';
          if (id.includes('node_modules/svelte')) return 'svelte-vendor';
          return undefined;
        },
      },
    },
  },
});
