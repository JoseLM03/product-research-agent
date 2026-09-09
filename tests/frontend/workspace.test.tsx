import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';
import Home from '@/app/page';
import { api } from '@/lib/api';

vi.mock('@/lib/api', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  api: vi.fn(),
}));
const request = vi.mocked(api);
const enabled = {
  configured: true,
  message: 'Enabled',
  daily_limit: 5,
  retention_days: 30,
};
const job = {
  id: '00000000-0000-4000-8000-000000000001',
  idea: 'compact coffee grinder',
  status: 'failed',
  created_at: 0,
  error: 'Model unavailable.',
};
beforeEach(() => {
  request.mockReset();
});

test('unconfigured provider is explicit and prevents submission', async () => {
  request.mockImplementation(async (path) =>
    path === '/session'
      ? { ...enabled, configured: false, message: 'Configure your providers.' }
      : [],
  );
  render(<Home />);
  expect(
    await screen.findByText('Configure your providers.'),
  ).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('What are you researching?'), {
    target: { value: 'coffee grinder' },
  });
  expect(screen.getByRole('button', { name: 'Start research' })).toBeDisabled();
  expect(
    request.mock.calls.some(([, options]) => options?.method === 'POST'),
  ).toBe(false);
});

test('submits actual user input and shows persisted failure without fabricating report', async () => {
  request.mockImplementation(async (path, options) => {
    if (path === '/session') return enabled;
    if (options?.method === 'POST') return job;
    if (path === '/research/' + job.id)
      return {
        ...job,
        report: null,
        inputs: { idea: job.idea, costs: null },
        events: [],
      };
    return [];
  });
  render(<Home />);
  await waitFor(() =>
    expect(
      screen.getByText('Up to 5 tasks per browser / day.'),
    ).toBeInTheDocument(),
  );
  fireEvent.change(screen.getByLabelText('What are you researching?'), {
    target: { value: job.idea },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Start research' }));
  expect(await screen.findByText('Model unavailable.')).toBeInTheDocument();
  expect(
    screen.getByText(/No validated report was produced/),
  ).toBeInTheDocument();
  const submitted = request.mock.calls.find(
    ([, options]) => options?.method === 'POST',
  );
  const body = submitted?.[1]?.body;
  if (typeof body !== 'string') throw new Error('Expected a JSON string body.');
  expect(JSON.parse(body)).toEqual({
    idea: job.idea,
    costs: null,
  });
});

test('existing active task is restored and blocks duplicate submissions', async () => {
  const active = { ...job, status: 'running', error: null };
  request.mockImplementation(async (path) =>
    path === '/session'
      ? enabled
      : path === '/research'
        ? [active]
        : {
            ...active,
            report: null,
            inputs: { idea: job.idea, costs: null },
            events: [],
          },
  );
  render(<Home />);
  expect(await screen.findByText(/The agent is gathering/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Start research' })).toBeDisabled();
});

test('server connection failures are actionable', async () => {
  request.mockImplementation(async () => {
    throw new Error('Server offline.');
  });
  render(<Home />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Server offline.');
  expect(screen.getByRole('button', { name: 'Reconnect' })).toBeInTheDocument();
});
