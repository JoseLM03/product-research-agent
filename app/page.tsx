'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ArrowUpRight,
  ScanSearch,
  ShieldCheck,
  FileSearch,
  Activity,
  Plus,
  Clock3,
} from 'lucide-react';
import { ResearchReport } from '@/components/research-report';
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from '@/components/ui/select';
import { Checkbox } from '@/components/ui/checkbox';
import { api, Costs, Detail, Job, Session } from '@/lib/api';
const blankCosts: Costs = {
  currency: 'USD',
  sale_price: '',
  unit_cost: '',
  shipping: '',
  other_costs: '',
  fee_percent: '',
};
const fields = [
  ['sale_price', 'Sale price'],
  ['unit_cost', 'Unit cost'],
  ['shipping', 'Shipping / unit'],
  ['other_costs', 'Other costs / unit'],
  ['fee_percent', 'Platform fee %'],
] as const;
export default function Home() {
  const [idea, setIdea] = useState('');
  const [costs, setCosts] = useState<Costs>(blankCosts);
  const [includeCosts, setIncludeCosts] = useState(false);
  const [session, setSession] = useState<Session | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [storedDetail, setDetail] = useState<Detail | null>(null);
  const detail = storedDetail?.id === selected ? storedDetail : null;
  const [error, setError] = useState('');
  const [pollError, setPollError] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const submitLock = useRef(false);
  const refresh = useCallback(async () => {
    const rows = await api<Job[]>('/research');
    setJobs(rows);
    return rows;
  }, []);
  const initialize = useCallback(async () => {
    try {
      const nextSession = await api<Session>('/session');
      setSession(nextSession);
      const rows = await refresh();
      setSelected(
        rows.find((j) => ['queued', 'running'].includes(j.status))?.id ?? null,
      );
    } catch (e) {
      setError(
        e instanceof Error ? e.message : 'Could not connect to the server.',
      );
    } finally {
      setLoading(false);
    }
  }, [refresh]);
  useEffect(() => {
    // oxlint-disable-next-line react/react-compiler -- HTTP bootstrap updates state on async completion, not from derived render data.
    void initialize();
  }, [initialize]);
  useEffect(() => {
    if (!selected) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    const poll = async () => {
      try {
        const next = await api<Detail>('/research/' + selected, {
          signal: controller.signal,
        });
        if (stopped) return;
        setDetail(next);
        setPollError('');
        await refresh();
        if (!stopped && ['queued', 'running'].includes(next.status))
          timer = setTimeout(poll, 2000);
      } catch (e) {
        if (stopped) return;
        setPollError(
          e instanceof Error ? e.message : 'Could not refresh research.',
        );
        timer = setTimeout(poll, 5000);
      }
    };
    void poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
      controller.abort();
    };
  }, [selected, refresh]);
  const active = jobs.some((j) => ['queued', 'running'].includes(j.status));
  useEffect(() => {
    if (selected || !active) return;
    const timer = setInterval(() => {
      void refresh().catch(() =>
        setPollError(
          'Could not refresh task status. Select the active task to retry.',
        ),
      );
    }, 3000);
    return () => clearInterval(timer);
  }, [selected, active, refresh]);
  async function start() {
    if (submitLock.current) return;
    submitLock.current = true;
    setBusy(true);
    setError('');
    try {
      const job = await api<Job>('/research', {
        method: 'POST',
        body: JSON.stringify({
          idea: idea.trim(),
          costs: includeCosts ? costs : null,
        }),
      });
      setJobs((previous) => [job, ...previous]);
      setSelected(job.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not start research.');
      await refresh().catch(() => {});
    } finally {
      setBusy(false);
      submitLock.current = false;
    }
  }
  useEffect(() => {
    type Context = {
      registerTool: (
        tool: {
          name: string;
          description: string;
          inputSchema: object;
          annotations: object;
          execute: (input: unknown) => unknown;
        },
        options: { signal: AbortSignal },
      ) => void | Promise<void>;
    };
    const context = (document as Document & { modelContext?: Context })
      .modelContext;
    if (!context) return;
    const life = new AbortController();
    try {
      void Promise.resolve(
        context.registerTool(
          {
            name: 'stage_research_idea',
            description:
              'Fill the product idea in the visible research brief. Does not start research or make provider requests.',
            inputSchema: {
              type: 'object',
              properties: {
                idea: { type: 'string', minLength: 5, maxLength: 500 },
              },
              required: ['idea'],
              additionalProperties: false,
            },
            annotations: { readOnlyHint: false, untrustedContentHint: true },
            execute(input) {
              const value = input as { idea?: unknown };
              if (
                !value ||
                typeof value.idea !== 'string' ||
                value.idea.trim().length < 5 ||
                value.idea.length > 500 ||
                Object.keys(value).some((k) => k !== 'idea')
              )
                throw new Error('Provide an idea of 5–500 characters.');
              setIdea(value.idea);
              setSelected(null);
              return { staged: true, idea: value.idea };
            },
          },
          { signal: life.signal },
        ),
      ).catch(() => {});
    } catch {
      /* Optional browser capability; normal form remains available. */
    }
    return () => life.abort();
  }, []);
  return (
    <main className="workspace">
      <header className="topbar">
        <button
          className="brand"
          type="button"
          onClick={() => {
            setSelected(null);
            setIdea('');
            setCosts(blankCosts);
            setIncludeCosts(false);
          }}
        >
          <ScanSearch size={25} /> Fieldwork <span>PRODUCT RESEARCH</span>
        </button>
        <span className="private">
          <ShieldCheck size={16} /> Private browser workspace
        </span>
      </header>
      <div className="work-grid">
        <aside className="history" aria-label="Research history">
          <button
            className="new"
            onClick={() => {
              setSelected(null);
              setIdea('');
              setCosts(blankCosts);
              setIncludeCosts(false);
              setError('');
            }}
          >
            <Plus size={18} /> New research
          </button>
          <h2>RESEARCH HISTORY</h2>
          {loading ? (
            <output className="muted">Connecting to your workspace…</output>
          ) : jobs.length ? (
            jobs.map((job) => (
              <button
                className={'job ' + (selected === job.id ? 'selected' : '')}
                aria-pressed={selected === job.id}
                key={job.id}
                onClick={() => setSelected(job.id)}
              >
                <strong>{job.idea}</strong>
                <span className="status">{job.status}</span>
              </button>
            ))
          ) : (
            <p className="muted">Your research will appear here.</p>
          )}
          <div className="privacy-note">
            <ShieldCheck size={20} />
            <p>
              History belongs to this browser and expires after{' '}
              {session?.retention_days ?? 30} days. Export reports before
              clearing cookies.
            </p>
          </div>
        </aside>
        <section className="main-panel">
          <div className="eyebrow">01 / RESEARCH BRIEF</div>
          <h1>
            Investigate your next
            <br />
            product idea.
          </h1>
          <p className="intro">
            Explore competitors, pricing, and market signals. Follow the
            evidence before making your next move.
          </p>
          <form
            className="brief"
            onSubmit={(e) => {
              e.preventDefault();
              void start();
            }}
          >
            <label htmlFor="idea">What are you researching?</label>
            <textarea
              id="idea"
              value={idea}
              onChange={(e) => setIdea(e.target.value)}
              placeholder="e.g. A repairable electric coffee grinder for small kitchens"
              required
              minLength={5}
              maxLength={500}
            />
            <details className="costs">
              <summary>Optional: add a cost scenario</summary>
              <p className="muted">
                Use known or explicitly assumed per-unit costs in one currency.
                These inputs are yours, not market research.
              </p>
              <label className="check-label">
                <Checkbox
                  checked={includeCosts}
                  onCheckedChange={(checked) =>
                    setIncludeCosts(checked === true)
                  }
                />{' '}
                Include a margin calculation
              </label>
              {includeCosts && (
                <div className="cost-grid">
                  <div>
                    <span id="currency-label">Currency</span>
                    <Select
                      value={costs.currency}
                      onValueChange={(value) =>
                        value && setCosts({ ...costs, currency: value })
                      }
                    >
                      <SelectTrigger aria-labelledby="currency-label">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent className="bg-white">
                        {['USD', 'EUR', 'GBP', 'CAD', 'AUD'].map((c) => (
                          <SelectItem key={c} value={c}>
                            {c}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  {fields.map(([key, label]) => (
                    <label key={key} htmlFor={key}>
                      {label}
                      <input
                        id={key}
                        required
                        type="number"
                        min={key === 'sale_price' ? '0.01' : '0'}
                        max={key === 'fee_percent' ? 100 : 1000000}
                        step="0.01"
                        value={costs[key]}
                        onChange={(e) =>
                          setCosts({ ...costs, [key]: e.target.value })
                        }
                      />
                    </label>
                  ))}
                </div>
              )}
            </details>
            <div className="brief-bottom">
              <span>
                {active
                  ? 'A research task is already active.'
                  : session
                    ? `Up to ${session.daily_limit} tasks per browser / day.`
                    : 'Connecting to the research service.'}
              </span>
              <button
                className="primary"
                type="submit"
                disabled={
                  !session?.configured ||
                  busy ||
                  active ||
                  idea.trim().length < 5
                }
              >
                {busy ? 'Starting…' : 'Start research'}{' '}
                <ArrowUpRight size={18} />
              </button>
            </div>
          </form>
          {error && (
            <div role="alert" className="notice error">
              {error}{' '}
              <button
                className="secondary"
                onClick={() => {
                  setError('');
                  setLoading(true);
                  void initialize();
                }}
              >
                Reconnect
              </button>
            </div>
          )}
          {session && !session.configured && (
            <output className="notice">{session.message}</output>
          )}
          {pollError && (
            <output className="notice error">
              {pollError} Retrying automatically; your task may still be
              running.
            </output>
          )}
          {selected && !detail && !pollError && (
            <output className="notice">Loading research…</output>
          )}
          {detail && (
            <ResearchReport
              key={detail.id}
              detail={detail}
              onDelete={async () => {
                try {
                  await api('/research/' + detail.id, {
                    method: 'DELETE',
                    body: '{}',
                  });
                  setSelected(null);
                  await refresh();
                } catch (e) {
                  setError(
                    e instanceof Error
                      ? e.message
                      : 'Could not delete research.',
                  );
                  throw e;
                }
              }}
            />
          )}
          {!selected && (
            <div className="method">
              <div>
                <FileSearch />
                <h3>Evidence first</h3>
                <p>
                  Claims link back to retrieved sources. Missing information
                  stays missing.
                </p>
              </div>
              <div>
                <Activity />
                <h3>A visible process</h3>
                <p>
                  See which tools the agent uses and where research encounters
                  limits.
                </p>
              </div>
              <div>
                <Clock3 />
                <h3>Bounded research</h3>
                <p>
                  A focused investigation with clear limits, rather than an
                  endless search.
                </p>
              </div>
            </div>
          )}
        </section>
      </div>
      <footer>
        FIELDWORK <span>AI-Powered E-Commerce Product Research Agent</span>
      </footer>
    </main>
  );
}
