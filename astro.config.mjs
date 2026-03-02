import { defineConfig } from 'astro/config';

export default defineConfig({
  site: 'https://il-bonvi.github.io',
  base: '/bonvi-race-archive',
  build: {
    assets: 'assets'
  }
});
