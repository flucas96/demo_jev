import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Checkbox, Drawer, Progress, Select } from '@mantine/core';
import { ArrowRight, Check, ChevronRight, CircleHelp, Clock3, Code2, Layers3, LoaderCircle, MoveHorizontal, Play, RotateCcw, Square, TriangleAlert } from 'lucide-react';
import { apiError, dollars, humanize, percent, seconds } from './api';
import { Inspector, OutputCards, PolicyPanel } from './ResultDetails';
import type { BatchEvent, BatchSummary, Evaluation, Health, Scenario, Ticket } from './types';

type TicketStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'interrupted';
interface TicketRun {
  status: TicketStatus;
  started_ms?: number;
  finished_ms?: number;
  evaluation?: Evaluation;
  error?: string;
}
type RunPhase = 'idle' | 'running' | 'cancelling' | 'finished' | 'cancelled' | 'error';

/** Reject malformed stream lines instead of silently claiming a successful run. */
function readEvent(line: string): BatchEvent {
  const value: unknown = JSON.parse(line);
  if (typeof value !== 'object' || value === null || !('type' in value)) throw new Error('The server sent an invalid queue event.');
  const event = value as Record<string, unknown>;
  const finite = (key: string) => typeof event[key] === 'number' && Number.isFinite(event[key]);
  switch (event.type) {
    case 'started':
      if (finite('total') && finite('concurrency')) return value as BatchEvent;
      break;
    case 'ticket_started':
      if (typeof event.ticket_id === 'string' && finite('started_ms') && finite('active')) return value as BatchEvent;
      break;
    case 'ticket_completed':
      if (typeof event.ticket_id === 'string' && finite('started_ms') && finite('finished_ms') && typeof event.evaluation === 'object' && event.evaluation !== null && 'response' in event.evaluation && 'decision' in event.evaluation) return value as BatchEvent;
      break;
    case 'ticket_failed':
      if (typeof event.ticket_id === 'string' && finite('started_ms') && finite('finished_ms') && typeof event.error === 'string') return value as BatchEvent;
      break;
    case 'finished':
      if (typeof event.summary === 'object' && event.summary !== null && 'elapsed_ms' in event.summary && 'succeeded' in event.summary) return value as BatchEvent;
      break;
  }
  throw new Error('The server sent an incomplete or unknown queue event.');
}

/** Describe both processing status and the completed Python routing action. */
function Status({ run }: { run: TicketRun | undefined }) {
  const status = run?.status ?? 'queued';
  const action = status === 'completed' ? run?.evaluation?.decision.action : null;
  const label = action === 'route' ? 'Routed' : action === 'review' ? 'Review' : action === 'escalate' ? 'Escalated' : status === 'running' ? 'Processing' : status === 'failed' ? 'Failed' : status === 'cancelled' ? 'Cancelled' : status === 'interrupted' ? 'Interrupted' : 'Queued';
  return <span className={`ticket-status ${action ?? status}`}>{status === 'running' ? <LoaderCircle size={12} className="spin" /> : action === 'route' ? <Check size={12} /> : action || status === 'failed' ? <TriangleAlert size={12} /> : <span className="status-dot" />}{label}</span>;
}

/** Run a bounded parallel Jira queue and display only observed timings. */
export default function BatchQueue({ tickets, scenario, health, onBusyChange, onGuide }: { tickets: Ticket[]; scenario: Scenario; health: Health | null; onBusyChange: (busy: boolean) => void; onGuide: () => void }) {
  const [count, setCount] = useState(Math.min(20, tickets.length));
  const [parallel, setParallel] = useState(true);
  const [runs, setRuns] = useState<Record<string, TicketRun>>({});
  const [phase, setPhase] = useState<RunPhase>('idle');
  const [summary, setSummary] = useState<BatchSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const controller = useRef<AbortController | null>(null);
  const runVersion = useRef(0);
  const startTime = useRef(0);
  const mounted = useRef(true);
  const activeTickets = tickets.slice(0, count);
  const busy = phase === 'running' || phase === 'cancelling';
  const completed = Object.values(runs).filter((run) => run.status === 'completed').length;
  const failed = Object.values(runs).filter((run) => run.status === 'failed').length;
  const running = Object.values(runs).filter((run) => run.status === 'running').length;
  const selectedTicket = tickets.find((ticket) => ticket.id === selectedId);
  const selectedRun = selectedId ? runs[selectedId] : undefined;
  const effectiveConcurrency = parallel ? count : 1;
  const hasRun = phase !== 'idle';
  const finalElapsed = summary?.elapsed_ms ?? elapsed;
  const timelineMax = Math.max(finalElapsed, 1);
  const counts = [...new Set([5, 10, 20, tickets.length].filter((value) => value <= tickets.length && value > 0))].sort((a, b) => a - b);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; runVersion.current += 1; controller.current?.abort(); };
  }, []);
  useEffect(() => {
    if (!busy) return;
    const timer = window.setInterval(() => setElapsed(performance.now() - startTime.current), 60);
    return () => window.clearInterval(timer);
  }, [busy]);

  function reset() { setRuns({}); setSummary(null); setError(null); setElapsed(0); setPhase('idle'); }
  async function runBatch() {
    if (controller.current || !activeTickets.length) return;
    const abort = new AbortController();
    controller.current = abort;
    const version = ++runVersion.current;
    let receivedSummary = false;
    let timedOut = false;
    let inactivityTimer: number | undefined;
    let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
    const isCurrent = () => mounted.current && runVersion.current === version;
    const ticketIds = activeTickets.map((ticket) => ticket.id);
    const knownIds = new Set(ticketIds);
    const touch = () => {
      window.clearTimeout(inactivityTimer);
      inactivityTimer = window.setTimeout(() => { timedOut = true; abort.abort(); }, 90000);
    };
    setRuns(Object.fromEntries(ticketIds.map((id) => [id, { status: 'queued' }])));
    setSummary(null); setError(null); setElapsed(0); setPhase('running'); onBusyChange(true);
    startTime.current = performance.now();
    touch();
    function receive(event: BatchEvent) {
      if (!isCurrent() || abort.signal.aborted) return;
      if (receivedSummary) throw new Error('The server sent events after the queue finished.');
      if ('ticket_id' in event && !knownIds.has(event.ticket_id)) throw new Error('The server returned an unexpected ticket.');
      switch (event.type) {
        case 'started':
          if (event.total !== ticketIds.length || event.concurrency !== effectiveConcurrency) throw new Error('The server started a different queue configuration.');
          break;
        case 'ticket_started':
          setRuns((previous) => ({ ...previous, [event.ticket_id]: { status: 'running', started_ms: event.started_ms } }));
          break;
        case 'ticket_completed':
          setRuns((previous) => ({ ...previous, [event.ticket_id]: { status: 'completed', started_ms: event.started_ms, finished_ms: event.finished_ms, evaluation: event.evaluation } }));
          break;
        case 'ticket_failed':
          setRuns((previous) => ({ ...previous, [event.ticket_id]: { status: 'failed', started_ms: event.started_ms, finished_ms: event.finished_ms, error: event.error } }));
          break;
        case 'finished':
          receivedSummary = true;
          setSummary(event.summary); setElapsed(event.summary.elapsed_ms);
          break;
      }
    }
    try {
      const response = await fetch('/api/triage/batch', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ticket_ids: ticketIds, concurrency: effectiveConcurrency, threshold: 0.8 }), signal: abort.signal });
      if (!response.ok) throw new Error(apiError(await response.json().catch(() => null), response.status));
      if (!response.body) throw new Error('This browser could not open the live result stream.');
      reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      while (true) {
        const chunk = await reader.read();
        if (chunk.done) break;
        touch();
        buffer += decoder.decode(chunk.value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';
        for (const line of lines) if (line.trim()) receive(readEvent(line));
      }
      buffer += decoder.decode();
      if (buffer.trim()) receive(readEvent(buffer));
      if (!receivedSummary) throw new Error('The connection ended before the queue finished. Completed results are preserved.');
      if (isCurrent()) setPhase('finished');
    } catch (failure: unknown) {
      if (isCurrent()) {
        const cancelled = abort.signal.aborted && !timedOut;
        setPhase(cancelled ? 'cancelled' : 'error');
        setError(cancelled ? null : timedOut ? 'No queue updates arrived for 90 seconds. The run was stopped; completed results are preserved.' : failure instanceof Error ? failure.message : 'The queue request failed.');
        setElapsed(performance.now() - startTime.current);
        setRuns((previous) => Object.fromEntries(Object.entries(previous).map(([id, run]) => [id, run.status === 'queued' || run.status === 'running' ? { ...run, status: cancelled ? 'cancelled' : 'interrupted' } : run])));
      }
    } finally {
      window.clearTimeout(inactivityTimer);
      abort.abort();
      await reader?.cancel().catch(() => undefined);
      reader?.releaseLock();
      if (isCurrent()) { controller.current = null; onBusyChange(false); }
    }
  }
  function cancel() { setPhase('cancelling'); controller.current?.abort(); }

  const progressText = busy ? `${completed + failed} of ${count} finished` : phase === 'finished' ? `${summary?.succeeded ?? completed} / ${count} processed` : phase === 'cancelled' ? `Run cancelled · ${completed} completed` : phase === 'error' ? `Run interrupted · ${completed} completed` : `${count} sample tickets ready`;

  return <section className="queue-workspace">
    <div className="queue-intro"><div><div className="eyebrow mono">LIVE WORKBENCH</div><h1>Jira triage, in parallel.</h1></div><div className="output-legend"><button type="button" onClick={onGuide}><span className="primitive-dot choice-dot" />Team <small>Choice</small></button><button type="button" onClick={onGuide}><span className="primitive-dot score-dot" />Impact <small>Score</small></button><button type="button" onClick={onGuide}><span className="primitive-dot noul-dot" />Outage <small>Noul</small></button></div></div>

    <div className="run-controls panel">
      <div className="control-fields"><Select label="Queue size" aria-label="Queue size" data={counts.map((value) => ({ value: String(value), label: `${value} tickets` }))} value={String(count)} onChange={(value) => { if (value) { reset(); setCount(Number(value)); } }} disabled={busy} allowDeselect={false} size="sm" /><Checkbox className="parallel-toggle" label="Parallel requests" checked={parallel} onChange={(event) => { reset(); setParallel(event.currentTarget.checked); }} disabled={busy} size="sm" /></div>
      <div className="run-explanation"><Layers3 size={17} /><div><strong>{parallel ? `All ${count} at once` : 'One at a time'}</strong><span>3 outputs / ticket</span></div></div>
      <Button className="run-queue-button" size="md" leftSection={busy ? <Square size={13} fill="currentColor" /> : hasRun ? <RotateCcw size={15} /> : <Play size={14} fill="currentColor" />} rightSection={busy ? undefined : <ArrowRight size={16} />} variant={busy ? 'outline' : 'filled'} disabled={!health?.configured || !tickets.length || phase === 'cancelling'} onClick={() => busy ? cancel() : void runBatch()}>{phase === 'cancelling' ? 'Stopping…' : busy ? 'Stop run' : hasRun ? `Run ${count} again` : `Triage ${count} tickets`}</Button>
    </div>

    <div className="performance-strip" aria-label="Run throughput and estimated cost">
      <div title="Successfully completed tickets divided by total batch wall time, including API and network latency."><span className="metric-label">Throughput</span><strong className="metric-value mono">{summary ? summary.tickets_per_second.toFixed(2) : '—'}<span>tickets / sec</span></strong></div>
      <div title={summary && summary.estimated_cost_usd == null ? 'Pricing is unavailable for this model or no successful usage was returned.' : 'Standard Jev 1.13 pricing: $0.042 per million input tokens; output tokens are free. Uses successful responses only. Failed or cancelled requests may still be billed; account-specific discounts are not included.'}><span className="metric-label cost-label">Est. cost<a className="pricing-link" href="https://docs.typesafe.ai/models" target="_blank" rel="noreferrer" aria-label="View Jev pricing"><CircleHelp size={12} /></a></span><strong className="metric-value mono">{dollars(summary?.estimated_cost_usd)}<span>USD</span></strong></div>
    </div>

    {error && <Alert className="error-alert" color="red" title="Queue interrupted" icon={<TriangleAlert size={17} />}>{error}</Alert>}
    {summary && summary.failed > 0 && <Alert className="error-alert" color="orange" title={`${summary.failed} ${summary.failed === 1 ? 'ticket failed' : 'tickets failed'}`} icon={<TriangleAlert size={17} />}>Successfully processed {summary.succeeded} of {summary.total}. Open failed rows to inspect the error, then run the queue again.</Alert>}

    <section className="queue-panel panel" aria-label="Ticket processing queue">
      <div className="queue-heading"><div><span className={`queue-live-dot ${busy ? 'active' : ''}`} /><h2>{progressText}</h2>{busy && <span className="inflight-label mono">{running} in flight</span>}</div><span className="queue-hint">Inspect a ticket<ChevronRight size={14} /></span><span className="mobile-scroll-hint"><MoveHorizontal size={15} aria-hidden="true" />Scroll for outputs</span></div>
      <Progress value={count ? ((completed + failed) / count) * 100 : 0} size={3} radius={0} color={failed ? 'orange' : 'vermilion'} aria-label="Queue completion" />
      <div className="queue-table-scroll">
        <table className="queue-table"><thead><tr><th className="ticket-column">Ticket</th><th>Status / route</th><th><span className="primitive-dot choice-dot" />Team</th><th><span className="primitive-dot score-dot" />Impact</th><th><span className="primitive-dot noul-dot" />Outage</th><th className="timeline-column">Request timeline</th><th aria-label="Inspect" /></tr></thead><tbody>
          {activeTickets.map((ticket) => {
            const run = runs[ticket.id];
            const answers = run?.evaluation?.response.answers;
            const start = run?.started_ms ?? 0;
            const finish = run?.finished_ms ?? (run?.status === 'running' ? elapsed : start);
            return <tr key={ticket.id} className={run?.status === 'running' ? 'processing-row' : ''} onClick={() => setSelectedId(ticket.id)}>
              <td><button type="button" className="ticket-open" onClick={(event) => { event.stopPropagation(); setSelectedId(ticket.id); }}><span className="ticket-key mono">{ticket.id}</span><span className="ticket-title">{ticket.title}</span></button></td>
              <td><Status run={run} /></td>
              <td>{answers ? <span className={`team-label team-${answers.choice.choice}`}>{humanize(answers.choice.choice)}</span> : <span className="empty-value">—</span>}</td>
              <td>{answers ? <span className={`impact-label impact-${Math.round(answers.score.score)}`}><span>{Number.isInteger(answers.score.score) ? answers.score.score : answers.score.score.toFixed(1)}</span><small>/ 4</small></span> : <span className="empty-value">—</span>}</td>
              <td>{answers ? <span className={`outage-label mono ${answers.noul.noul >= 0.8 ? 'high' : ''}`}>{percent(answers.noul.noul)}</span> : <span className="empty-value">—</span>}</td>
              <td><div className="ticket-timeline" title={run?.started_ms === undefined ? 'Not started' : `Started at ${seconds(start)}${run.finished_ms === undefined ? '' : `; finished at ${seconds(finish)}`}`}><span className={`timeline-bar ${run?.status ?? 'queued'}`} style={{ left: `${Math.min(100, (start / timelineMax) * 100)}%`, width: `${Math.min(100, Math.max(0, ((finish - start) / timelineMax) * 100))}%` }} /></div></td>
              <td><ChevronRight size={14} className="row-chevron" /></td>
            </tr>;
          })}
        </tbody></table>
      </div>
      <div className="queue-footer"><span>Sample tickets · no Jira changes</span><span className="timeline-legend"><span />Request timing</span></div>
    </section>

    <div className="queue-bottom"><p><Clock3 size={15} /><span>Compare <strong>sequential</strong> → <strong>all {count} in parallel</strong></span></p><button type="button" onClick={onGuide}><CircleHelp size={14} />Output guide</button></div>
    <details className="batch-code panel"><summary><span><Code2 size={16} />The parallelism is Python</span><span className="mono">asyncio + bounded concurrency</span></summary><div className="batch-code-copy"><p>The Python server limits in-flight Jev requests and streams each completed ticket to this queue. The configured limit controls concurrency; actual throughput depends on API response times and capacity.</p><div className="code-view"><pre><code>{`import asyncio\n\nfrom jev_demo.catalog import SCENARIOS\nfrom jev_demo.models import EvaluateRequest\nfrom jev_demo.service import evaluate\n\n# Inside your async handler, with its shared client and settings.\nsemaphore = asyncio.Semaphore(${effectiveConcurrency})\n\nasync def triage(ticket):\n    async with semaphore:\n        return await evaluate(\n            client, settings, SCENARIOS["triage"],\n            EvaluateRequest(\n                scenario_id="triage", text=ticket.text, threshold=0.8\n            ),\n        )\n\n# Process completions as they arrive; don't wait for the slowest.\ntasks = [asyncio.create_task(triage(ticket)) for ticket in tickets]\nfor task in asyncio.as_completed(tasks):\n    result = await task\n    # Stream the typed outputs and Python routing decision.\n`}</code></pre></div><p className="code-caption">Conceptual concurrency pattern. Inspect a ticket for its actual request, response, and executable Python example.</p></div></details>
    {summary && <div className="batch-usage mono">{summary.model ?? health?.model} · {summary.input_tokens.toLocaleString()} input tokens · {summary.output_tokens.toLocaleString()} output tokens</div>}

    <Drawer opened={selectedTicket !== undefined} onClose={() => setSelectedId(null)} position="right" size="min(820px, 100vw)" closeButtonProps={{ 'aria-label': 'Close ticket details' }} title={<span className="drawer-ticket-id mono">{selectedTicket?.id} <span>/ ticket inspection</span></span>} classNames={{ content: 'ticket-drawer', header: 'drawer-header' }}>
      {selectedTicket && <div className="ticket-detail"><div className="detail-heading"><h2>{selectedTicket.title}</h2><Status run={selectedRun} /></div><div className="detail-meta"><span>{selectedTicket.tag}</span>{selectedRun?.evaluation && <span className="mono">{seconds(selectedRun.evaluation.elapsed_ms)} · live Jev response</span>}</div><details className="source-ticket" open><summary>Original ticket text</summary><pre>{selectedTicket.text}</pre></details>
        {selectedRun?.error && <Alert color="red" title="Ticket request failed" icon={<TriangleAlert size={16} />}>{selectedRun.error}</Alert>}
        <OutputCards scenario={scenario} evaluation={selectedRun?.evaluation ?? null} loading={selectedRun?.status === 'running'} />
        <PolicyPanel scenario={scenario} decision={selectedRun?.evaluation?.decision} threshold={selectedRun?.evaluation?.decision.threshold ?? 0.8} />
        <p className="output-caveat">Confidence describes the output distribution; it is not measured accuracy.</p>
        <Inspector key={selectedTicket.id} scenario={scenario} text={selectedTicket.text} model={health?.model ?? 'jev'} evaluation={selectedRun?.evaluation ?? null} threshold={selectedRun?.evaluation?.decision.threshold ?? 0.8} />
      </div>}
    </Drawer>
  </section>;
}
