import { afterEach, expect, test, vi } from 'vitest';
import { api } from '@/lib/api';
afterEach(() => vi.unstubAllGlobals());

test('same-origin requests retain session and send JSON', async () => {
  const fetch = vi
    .fn()
    .mockResolvedValue({ ok: true, json: async () => ({ id: 'task' }) });
  vi.stubGlobal('fetch', fetch);
  expect(await api('/research', { method: 'POST', body: '{}' })).toEqual({
    id: 'task',
  });
  expect(fetch).toHaveBeenCalledWith(
    '/api/research',
    expect.objectContaining({
      credentials: 'same-origin',
      method: 'POST',
      headers: expect.any(Headers),
    }),
  );
});
test('rate limit message is preserved', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: false,
      status: 429,
      json: async () => ({ detail: 'Daily research limit reached.' }),
    }),
  );
  await expect(api('/research')).rejects.toThrow(
    'Daily research limit reached.',
  );
});
test('non-JSON proxy failures do not become successful responses', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: false,
      status: 502,
      json: async () => {
        throw new Error('HTML');
      },
    }),
  );
  await expect(api('/research')).rejects.toThrow('Request failed (502)');
});
