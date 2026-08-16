import { defineConfig } from 'vite';

export default defineConfig({
  build: {
    outDir: 'dist',
    lib: {
      entry: 'src/index.ts',
      formats: ['es'],
      fileName: () => 'vanna-components.js',
    },
    rollupOptions: {
      // Remove external to bundle lit with the components
      // external: /^lit/,
    },
  },
  preview: {
    port: 9876,
    strictPort: true,
  },
});
