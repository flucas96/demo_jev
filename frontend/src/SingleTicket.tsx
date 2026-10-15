import { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Button, SegmentedControl, Select, Textarea } from '@mantine/core';
import { ArrowRight, Play, TriangleAlert } from 'lucide-react';
import { api } from './api';
import { Inspector, OutputCards, PolicyPanel } from './ResultDetails';
import type { Decision, Evaluation, Health, Scenario } from './types';

/** Evaluate editable sample or pasted text with all three Jev primitives. */
export default function SingleTicket({ scenario, health }: { scenario: Scenario; health: Health | null }) {
  const [text, setText] = useState(scenario.examples[0]?.text ?? '');
  const [exampleId, setExampleId] = useState<string | null>(scenario.examples[0]?.id ?? null);
  const [inputMode, setInputMode] = useState('samples');
  const [threshold, setThreshold] = useState(0.8);
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const [loading, setLoading] = useState(false);
  const [policyLoading, setPolicyLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const activeRequest = useRef<AbortController | null>(null);
  const activePolicy = useRef<AbortController | null>(null);
  const version = useRef(0);
  const policyVersion = useRef(0);
  const clear = useCallback(() => {
    activeRequest.current?.abort();
    activePolicy.current?.abort();
    version.current += 1;
    policyVersion.current += 1;
    setEvaluation(null);
    setLoading(false);
    setPolicyLoading(false);
    setError(null);
  }, []);
  useEffect(() => () => { activeRequest.current?.abort(); activePolicy.current?.abort(); }, []);

  function editText(value: string) { clear(); setText(value); setExampleId(null); }
  function selectExample(id: string) {
    const example = scenario.examples.find((item) => item.id === id);
    if (!example) return;
    clear(); setText(example.text); setExampleId(example.id);
  }
  async function evaluate() {
    if (!text.trim() || loading) return;
    clear();
    const current = version.current;
    const controller = new AbortController();
    activeRequest.current = controller;
    setLoading(true);
    try {
      const result = await api<Evaluation>('/api/evaluate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ scenario_id: scenario.id, text, threshold }), signal: controller.signal });
      if (!controller.signal.aborted && current === version.current) setEvaluation(result);
    } catch (failure: unknown) {
      if (!controller.signal.aborted && current === version.current) setError(failure instanceof Error ? failure.message : 'Evaluation failed. Try again.');
    } finally {
      if (!controller.signal.aborted && current === version.current) setLoading(false);
    }
  }
  async function updatePolicy(value: number) {
    if (!evaluation) return;
    activePolicy.current?.abort();
    const controller = new AbortController();
    activePolicy.current = controller;
    const current = ++policyVersion.current;
    setPolicyLoading(true); setError(null);
    try {
      const decision = await api<Decision>('/api/policy', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ scenario_id: scenario.id, threshold: value, response: evaluation.response }), signal: controller.signal });
      if (!controller.signal.aborted && current === policyVersion.current) setEvaluation((previous) => previous ? { ...previous, decision } : null);
    } catch (failure: unknown) {
      if (!controller.signal.aborted && current === policyVersion.current) setError(failure instanceof Error ? failure.message : 'Policy update failed.');
    } finally {
      if (!controller.signal.aborted && current === policyVersion.current) setPolicyLoading(false);
    }
  }

  return <div className="single-workspace">
    <div className="single-intro"><div><h2>{scenario.id === 'triage' ? 'One ticket, every signal.' : scenario.title}</h2>{scenario.id !== 'triage' && <p>{scenario.description}</p>}</div></div>
    <div className="workbench">
      <section className="input-panel panel">
        <div className="panel-heading"><h3>{scenario.id === 'triage' ? 'Ticket text' : 'Source text'}</h3><span className="subtle-label">Editable</span></div>
        <div className="input-content">
          <SegmentedControl fullWidth size="xs" value={inputMode} onChange={setInputMode} data={[{ value: 'samples', label: scenario.id === 'triage' ? 'Sample tickets' : 'Sample inputs' }, { value: 'paste', label: 'Paste your text' }]} />
          {inputMode === 'samples' && <Select className="sample-selector" label={scenario.id === 'triage' ? 'Sample ticket' : 'Sample input'} aria-label="Select sample" data={scenario.examples.map((example) => ({ value: example.id, label: example.title }))} value={exampleId} onChange={(value) => { if (value) selectExample(value); }} allowDeselect={false} size="sm" />}
          <Textarea id="input-text" aria-label={scenario.id === 'triage' ? 'Ticket title and description' : 'Source text'} value={text} onChange={(event) => editText(event.currentTarget.value)} placeholder="Paste the text you want Jev to evaluate…" minRows={9} autosize maxRows={17} maxLength={16000} classNames={{ input: 'ticket-textarea' }} />
          <div className="editor-footer"><span>Text only</span><span className="mono">{text.length.toLocaleString()} chars</span></div>
          <Button fullWidth size="md" leftSection={<Play size={14} fill="currentColor" />} rightSection={<ArrowRight size={16} />} loading={loading} disabled={!text.trim() || !health?.configured} onClick={() => void evaluate()}>{evaluation ? 'Evaluate again' : 'Evaluate with Jev'}</Button>

        </div>
      </section>
      <section className="output-panel">
        <OutputCards scenario={scenario} evaluation={evaluation} loading={loading} />
        <PolicyPanel scenario={scenario} decision={evaluation?.decision} threshold={threshold} onThresholdChange={setThreshold} onThresholdCommit={(value) => void updatePolicy(value)} loading={loading} policyLoading={policyLoading} />
        <p className="output-caveat">Confidence describes the output distribution; it is not measured accuracy.</p>
      </section>
    </div>
    {error && <Alert color="red" title="Request could not be completed" icon={<TriangleAlert size={17} />} className="error-alert">{error}</Alert>}
    <Inspector key={scenario.id} scenario={scenario} text={text} model={health?.model ?? 'jev'} evaluation={evaluation} threshold={threshold} />
  </div>;
}
