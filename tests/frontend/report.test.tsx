import { render, screen, within } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import { ResearchReport } from '@/components/research-report';
import type { Detail } from '@/lib/api';

const detail: Detail = {
  id: '00000000-0000-4000-8000-000000000002',
  idea: 'portable heated lunch box',
  status: 'completed',
  created_at: 0,
  error: null,
  inputs: { idea: 'portable heated lunch box', costs: null },
  events: [],
  report: {
    overview: {
      text: 'Source S1 states (unverified excerpt): “Workers often lack microwave access.”',
      citations: [
        { source_id: 'S1', quote: 'Workers often lack microwave access.' },
      ],
    },
    observations: [
      {
        text: 'Source S1 states (unverified excerpt): “The battery lasts two meals.”',
        citations: [{ source_id: 'S1', quote: 'The battery lasts two meals.' }],
      },
    ],
    competitors: [
      {
        text: 'Source S2 states (unverified excerpt): “A corded model uses a 12-volt plug.”',
        citations: [
          { source_id: 'S2', quote: 'A corded model uses a 12-volt plug.' },
        ],
      },
    ],
    rationale: {
      text: 'Source S2 states (unverified excerpt): “The container holds six cups.”',
      citations: [{ source_id: 'S2', quote: 'The container holds six cups.' }],
    },
    opportunities: [
      {
        text: 'Test whether workers prefer cordless lunch boxes.',
        validation_step: 'Ask workers which option they would choose.',
      },
      {
        text: 'Test whether the cost premium for cordless models creates a barrier for entry-level construction workers.',
        validation_step: 'Ask workers to compare corded and cordless prices.',
      },
    ],
    risks: [
      {
        text: 'Test whether a six-cup box is too large.',
        validation_step: 'Let workers pack one normal lunch in each size.',
      },
      {
        text: 'Test whether cordless models are practical on remote jobsites.',
        validation_step: 'Ask workers to try both models on a jobsite.',
      },
    ],
    assessment: 'mixed_signals',
    limitations: ['Search results were limited to snippets.'],
    sources: [
      {
        id: 'S1',
        title: 'Worker survey',
        url: 'https://example.com/one',
        snippet: 'Workers often lack microwave access.',
        retrieved_at: '2026-09-26T12:00:00Z',
        query: 'heated lunch box workers',
      },
      {
        id: 'S2',
        title: 'Product listing',
        url: 'https://example.com/two',
        snippet: 'A corded model uses a 12-volt plug.',
        retrieved_at: '2026-09-26T12:00:00Z',
        query: 'heated lunch box competitors',
      },
    ],
    price_mentions: [{ source_id: 'S3', text: '$59.99' }],
    calculation: null,
  },
};

test('presents evidence, status, and hypotheses in plain language', () => {
  const { container, rerender } = render(
    <ResearchReport detail={detail} onDelete={vi.fn()} />,
  );

  expect(
    screen.getByRole('button', {
      name: 'Source 1 (S1) · Unverified excerpt',
    }),
  ).toBeInTheDocument();
  expect(screen.getAllByRole('button', { name: 'S1' })).toHaveLength(1);
  expect(
    screen.getByRole('button', {
      name: 'Source 2 (S2) · Unverified excerpt',
    }),
  ).toBeInTheDocument();
  expect(screen.getAllByRole('button', { name: 'S2' })).toHaveLength(1);
  expect(
    screen.getByRole('button', {
      name: 'Source 3 (S3) · Unverified excerpt',
    }),
  ).toBeInTheDocument();
  expect(screen.queryByText(/Source S1 states/)).not.toBeInTheDocument();
  expect(
    screen.getByText('Workers often lack microwave access.'),
  ).toBeInTheDocument();

  const status = container.querySelector('.assess');
  expect(status).not.toBeNull();
  expect(
    within(status as HTMLElement).getByText('Limited'),
  ).toBeInTheDocument();
  expect(
    within(status as HTMLElement).getByText(/important questions still need/),
  ).toBeInTheDocument();
  expect(
    within(status as HTMLElement).queryByText('The container holds six cups.'),
  ).not.toBeInTheDocument();
  expect(screen.getByText('Additional evidence')).toBeInTheDocument();

  expect(screen.getByText('Opportunities to test')).toBeInTheDocument();
  expect(screen.getByText('Risks to test')).toBeInTheDocument();
  expect(screen.getAllByText('Idea to test:')).toHaveLength(4);
  expect(screen.getAllByText('How to test:')).toHaveLength(4);
  expect(
    screen.getByText('Would workers prefer cordless lunch boxes?'),
  ).toBeInTheDocument();
  expect(
    screen.getByText('Would a six-cup box be too large?'),
  ).toBeInTheDocument();
  expect(
    screen.getByText('Would cordless models be practical on remote jobsites?'),
  ).toBeInTheDocument();
  expect(
    screen.getByText(
      'Would the cost premium for cordless models create a barrier for entry-level construction workers?',
    ),
  ).toBeInTheDocument();
  expect(screen.queryByText('Validate:')).not.toBeInTheDocument();

  rerender(
    <ResearchReport
      detail={{
        ...detail,
        report: { ...detail.report!, assessment: 'insufficient_evidence' },
      }}
      onDelete={vi.fn()}
    />,
  );
  expect(
    screen.getByText(
      'The report did not find enough usable evidence to make a stronger recommendation.',
    ),
  ).toBeInTheDocument();
});
