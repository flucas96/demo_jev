import { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Button, Loader, Menu } from '@mantine/core';
import { ArrowUpRight, BookOpen, ChevronDown, CircleHelp, Inbox, Gamepad2, Search, ShieldCheck, TriangleAlert } from 'lucide-react';
import { api } from './api';
import BatchQueue from './BatchQueue';
import Runner from './runner/Runner';
import Snake from './snake/Snake';
import { PrimitiveGuide } from './ResultDetails';
import SingleTicket from './SingleTicket';
import type { Health, Scenario, Ticket } from './types';
import DemoHome from './brand/DemoHome';

/** A Jira-first workspace for measured parallel inference and typed decisions. */
export default function App() {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [booting, setBooting] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState(location.hash.slice(1) || 'home');
  const [busy, setBusy] = useState(false);
  const [guideOpen, setGuideOpen] = useState(false);
  const request = useRef<AbortController | null>(null);
  const load = useCallback(async () => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setBooting(true); setError(null);
    try {
      const [available, status, samples] = await Promise.all([api<Scenario[]>('/api/scenarios', { signal: controller.signal }), api<Health>('/api/health', { signal: controller.signal }), api<Ticket[]>('/api/triage/tickets', { signal: controller.signal })]);
      if (controller.signal.aborted) return;
      if (!available.some((item) => item.id === 'triage') || !samples.length) throw new Error('The Python server has no Jira sample queue configured.');
      setScenarios(available); setHealth(status); setTickets(samples);
    } catch (failure: unknown) {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : 'Could not connect to the Python server.');
    } finally {
      if (!controller.signal.aborted) setBooting(false);
    }
  }, []);
  useEffect(() => { void load(); return () => request.current?.abort(); }, [load]);
  useEffect(() => {
    const navigate = () => setView(location.hash.slice(1) || 'home');
    window.addEventListener('hashchange', navigate);
    return () => window.removeEventListener('hashchange', navigate);
  }, []);
  const triage = scenarios.find((item) => item.id === 'triage');
  const current = scenarios.find((item) => item.id === view);
  const extras = scenarios.filter((item) => item.id !== 'triage');

  if (view === 'home') return <DemoHome />;

  return <div className="app-shell">
    <a className="skip-link" href="#main">Skip to queue</a>
    <header className="app-header"><div className="header-brand"><a className="wordmark" href="https://typesafe.ai/" target="_blank" rel="noreferrer" aria-label="Jev by TypeSafe">jev<span>.</span></a><span className="brand-divider" /><div className="workspace-name">{(view === 'runner' || view === 'snake') ? <Gamepad2 size={17} /> : <Inbox size={17} />}{view === 'snake' ? 'Snake' : view === 'runner' ? 'Lantern Run' : 'Jira triage'}<span className="demo-tag mono">DEMO</span></div></div><div className="header-right"><span className={`connection-status ${health?.configured ? 'configured' : ''}`}><span />{booting ? 'Connecting' : health?.configured ? 'API configured' : 'API not configured'}</span><a className="docs-link" href="https://docs.typesafe.ai/" target="_blank" rel="noreferrer">API docs<ArrowUpRight size={14} /></a></div></header>
    <div className="workspace-nav"><nav aria-label="Demo view"><button className={view === 'queue' ? 'active' : ''} type="button" onClick={() => setView('queue')} disabled={busy && view !== 'queue'}>Parallel queue</button><button className={view === 'triage' ? 'active' : ''} type="button" onClick={() => setView('triage')} disabled={busy}>Single ticket</button><button className={view === 'runner' ? 'active' : ''} type="button" onClick={() => setView('runner')} disabled={busy}><Gamepad2 size={14} />Lantern Run</button><button className={view === 'snake' ? 'active' : ''} type="button" onClick={() => setView('snake')} disabled={busy}><Gamepad2 size={14} />Snake</button><Menu position="bottom-start" shadow="sm" width={220}><Menu.Target><button className={current && current.id !== 'triage' ? 'active' : ''} type="button" disabled={busy}>{current && current.id !== 'triage' ? current.title : 'More examples'}<ChevronDown size={13} /></button></Menu.Target><Menu.Dropdown><Menu.Label>Other Jev applications</Menu.Label>{extras.map((scenario) => <Menu.Item key={scenario.id} leftSection={scenario.id === 'review' ? <ShieldCheck size={15} /> : <Search size={15} />} onClick={() => setView(scenario.id)}>{scenario.title}</Menu.Item>)}</Menu.Dropdown></Menu></nav><button className="guide-button" type="button" onClick={() => setGuideOpen(true)}><BookOpen size={14} />Output guide</button></div>
    <main id="main" className="main-content">
      {booting && <div className="boot-state" role="status"><Loader size="sm" color="gray" />Connecting to the Python workbench…</div>}
      {error && <Alert title="Workbench unavailable" icon={<TriangleAlert size={18} />} color="red" className="error-alert"><p>{error}</p><Button size="xs" variant="outline" onClick={() => void load()}>Reconnect</Button></Alert>}
      {!booting && !error && <>
        {!health?.configured && <Alert color="orange" title="Server-side API key required" icon={<TriangleAlert size={17} />} className="error-alert">Set TYPESAFE_API_KEY in the Python server environment, then restart the server.</Alert>}
        {triage && <div hidden={view !== 'queue'}><BatchQueue tickets={tickets} scenario={triage} health={health} onBusyChange={setBusy} onGuide={() => setGuideOpen(true)} /></div>}
        {view === 'runner' && <Runner />}
        {view === 'snake' && <Snake />}
        {current && <SingleTicket key={current.id} scenario={current} health={health} />}
      </>}
      <footer className="page-footer"><span>Jev by TypeSafe</span><span><CircleHelp size={12} />Live timings</span></footer>
    </main>
    <PrimitiveGuide opened={guideOpen} onClose={() => setGuideOpen(false)} />
  </div>;
}
