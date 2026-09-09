import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';

export default defineConfig({
  resolve: { alias: { '@': fileURLToPath(new URL('.', import.meta.url)) } },
  test: {
    environment: 'jsdom',
    include: ['tests/frontend/**/*.test.ts?(x)'],
    setupFiles: ['tests/frontend/setup.ts'],
    restoreMocks: true,
    clearMocks: true,
  },
});
