import { defineConfig } from 'astro/config';

export default defineConfig({
  site: 'https://il-bonvi.github.io',
  base: '/bonvi-race-database',
  build: {
    assets: 'assets'
  }
});
