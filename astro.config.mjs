import { defineConfig } from 'astro/config';

const isProduction = process.env.NODE_ENV === 'production';

export default defineConfig({
  site: 'https://il-bonvi.github.io',
  base: isProduction ? '/archivio-prototipo' : '/',

  build: {
    assets: 'assets'
  }
});
