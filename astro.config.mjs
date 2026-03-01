import { defineConfig } from 'astro/config';

export default defineConfig({
  site: 'https://il-bonvi.github.io',
  base: process.env.GITHUB_ACTIONS ? '/archivio-prototipo' : undefined,

  build: {
    assets: 'assets'
  }
});
