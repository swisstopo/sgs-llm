/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import { viteStaticCopy } from 'vite-plugin-static-copy';

export default defineConfig({
  server: {
    // The curated layer catalog (layers/*.json5) lives at the repository root,
    // one level above this Vite root.
    fs: { allow: ['..'] },
  },
  plugins: [
    // @swissgeol/ui-core resolves its fonts and icons from the absolute /assets
    // path, so its packaged assets must be served from there (asset-copy target
    // follows swisstopo/swissgeol-viewer-suite's Vite setup).
    viteStaticCopy({
      targets: [
        {
          src: 'node_modules/@swissgeol/ui-core/dist/swissgeol-ui-core/assets/**/*',
          dest: 'assets',
          // Strip the node_modules/.../assets prefix so files land at
          // /assets/fonts/... exactly as the ui-core CSS references them.
          rename: { stripBase: 6 },
        },
      ],
    }),
  ],
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
});
