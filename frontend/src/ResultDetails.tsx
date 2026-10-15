import { useState } from 'react';
import { Button, Loader, Modal, Slider, Tabs } from '@mantine/core';
import { ArrowUpRight, Check, CheckCheck, Copy, GitBranch, SlidersHorizontal, Terminal, TriangleAlert } from 'lucide-react';
import { dollars, humanize, percent, seconds } from './api';
import type { Decision, Evaluation, Scenario } from './types';

/** Show every returned label, including unlikely alternatives. */
function Distribution({ values, selected, ordered = false }: { values: Record<string, number>; selected?: string; ordered?: boolean }) {
  return <div className="distribution">
    {Object.entries(values).sort((a, b) => ordered ? Number(a[0]) - Number(b[0]) : b[1] - a[1]).map(([label, value]) => <div className={`distribution-row ${selected === label ? 'selected' : ''}`} key={label}>
      <div className="distribution-label"><span>{humanize(label)}</span><span className="mono">{percent(value)}</span></div>
      <div className="distribution-track"><span style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }} /></div>
    </div>)}
  </div>;
}

/** Explain an output before a live result arrives. */
function Awaiting({ description, loading }: { description: string; loading: boolean }) {
  return <div className="awaiting" title={description}><div>{loading ? <Loader size={20} color="gray" /> : '—'}</div><p>{loading ? 'Evaluating…' : 'Awaiting result'}</p></div>;
}

/** Present the same three typed signals in every demonstration. */
export function OutputCards({ scenario, evaluation, loading = false }: { scenario: Scenario; evaluation: Evaluation | null; loading?: boolean }) {
  const answers = evaluation?.response.answers;
  return <div className="result-grid" aria-busy={loading}>
    <article className="result-card choice-card">
      <div className="result-type"><span className="primitive-dot choice-dot" /><h3>Choice</h3><span className="mono">ENUM</span></div>
      <p className="result-question">{scenario.choice_label}</p>
      {answers ? <><div className="choice-value">{humanize(answers.choice.choice)}</div><div className="confidence-label"><span>Confidence</span><strong className="mono">{percent(answers.choice.confidence)}</strong></div><Distribution values={answers.choice.probabilities} selected={answers.choice.choice} /></> : <Awaiting description="Route to a named team." loading={loading} />}

    </article>
    <article className="result-card score-card">
      <div className="result-type"><span className="primitive-dot score-dot" /><h3>Score</h3><span className="mono">ORDINAL</span></div>
      <p className="result-question">{scenario.score_label}</p>
      {answers ? <><div className="score-value"><span>{Number.isInteger(answers.score.score) ? answers.score.score : answers.score.score.toFixed(2)}</span><span className="score-denominator">/ {scenario.score_labels.length - 1}</span></div><div className="confidence-label"><span>Confidence</span><strong className="mono">{percent(answers.score.confidence)}</strong></div><Distribution values={answers.score.probabilities} selected={String(answers.score.score)} ordered /><details className="rubric"><summary>Scoring rubric</summary><ol start={0}>{scenario.questions.score.criteria.map((label, index) => <li key={label}><span className="mono">{index}</span>{label}</li>)}</ol></details></> : <Awaiting description="Assess impact on a defined scale." loading={loading} />}

    </article>
    <article className="result-card noul-card">
      <div className="result-type"><span className="primitive-dot noul-dot" /><h3>Noul</h3><span className="mono">P(YES)</span></div>
      <p className="result-question">{scenario.noul_label}</p>
      {answers ? <><div className="noul-value">{percent(answers.noul.noul)}</div><div className="noul-subtitle">Probability of yes</div><div className="noul-meter"><span style={{ width: `${Math.max(0, Math.min(1, answers.noul.noul)) * 100}%` }} /></div><div className="noul-scale mono"><span>0% · No</span><span>Yes · 100%</span></div></> : <Awaiting description="Estimate the probability of yes." loading={loading} />}

    </article>
  </div>;
}

/** Show the deterministic application policy, separate from model output. */
export function PolicyPanel({ scenario, decision, threshold, onThresholdChange, onThresholdCommit, loading = false, policyLoading = false }: { scenario: Scenario; decision?: Decision; threshold: number; onThresholdChange?: (value: number) => void; onThresholdCommit?: (value: number) => void; loading?: boolean; policyLoading?: boolean }) {
  return <section className={`policy-panel ${decision ? `decision-${decision.action}` : ''}`}>
    <div className="policy-top"><div><div className="micro-label mono"><GitBranch size={13} /> PYTHON ROUTING POLICY</div><h3>{decision?.label ?? 'Your rules make the final call.'}</h3></div>{decision && <span className={`decision-badge ${decision.action}`}>{decision.action === 'route' ? <Check size={12} /> : <TriangleAlert size={12} />}{humanize(decision.action)}</span>}</div>
    <p className="policy-description">{decision ? decision.destination : scenario.policy_description}</p>
    {onThresholdChange && <div className="policy-controls"><div className="threshold-label"><label id="threshold-label">Confidence threshold</label><span className="mono">{percent(threshold)}</span></div><Slider aria-labelledby="threshold-label" value={threshold} onChange={onThresholdChange} onChangeEnd={onThresholdCommit} min={0} max={1} step={0.01} disabled={loading} label={percent} size="sm" className="threshold-slider" /><div className="policy-note">{policyLoading ? <><Loader size={11} />Recalculating policy…</> : decision && decision.threshold !== threshold ? <><TriangleAlert size={12} />Showing policy at {percent(decision.threshold)}. Move the slider to retry.</> : <><SlidersHorizontal size={12} />Adjust the threshold without another model call.</>}</div></div>}
    {decision && <details className="policy-trace"><summary>Routing reasons</summary>{decision.reasons.map((reason) => <p key={reason}><CheckCheck size={13} /><span>{reason}</span></p>)}</details>}
    <div className="simulation-note">{scenario.id === 'triage' ? 'Simulated Jira assignment · no Jira changes' : 'Demo decision · no external action'}{!onThresholdChange && <span>Threshold {percent(threshold)}</span>}</div>
  </section>;
}

/** Produce an executable server-side example using the same Python policy. */
function pythonExample(scenario: Scenario, text: string, model: string, threshold: number): string {
  const request = { model, state: text, questions: scenario.questions };
  const literal = JSON.stringify(request, null, 2).replaceAll('\\', '\\\\').replaceAll("'", "\\'");
  return `# Run from this project: uv run --env-file .env python evaluate.py\nimport json\nimport os\n\nimport httpx\n\nfrom jev_demo.catalog import SCENARIOS\nfrom jev_demo.models import JevResponse\nfrom jev_demo.policy import decide\n\npayload = json.loads('''${literal}''')\n\nresponse = httpx.post(\n    "https://api.typesafe.ai/v1/systemone",\n    headers={"Authorization": f"Bearer {os.environ['TYPESAFE_API_KEY']}"},\n    json=payload,\n    timeout=60.0,\n)\nresponse.raise_for_status()\nresult = JevResponse.model_validate(response.json())\n\ndecision = decide(SCENARIOS["${scenario.id}"], result, threshold=${threshold.toFixed(2)})\nprint(decision.model_dump_json(indent=2))\n`;
}

/** Keep request, response, and executable Python accessible on demand. */
export function Inspector({ scenario, text, model, evaluation, threshold }: { scenario: Scenario; text: string; model: string; evaluation: Evaluation | null; threshold: number }) {
  const [tab, setTab] = useState<string | null>('request');
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState(false);
  const content = tab === 'python' ? pythonExample(scenario, text, model, threshold) : tab === 'response' ? evaluation ? JSON.stringify(evaluation.response, null, 2) : '// Run a ticket to inspect the live API response.' : JSON.stringify(evaluation?.request ?? { model, state: text, questions: scenario.questions }, null, 2);
  async function copy() {
    try { await navigator.clipboard.writeText(content); setCopied(true); setCopyError(false); }
    catch { setCopyError(true); }
  }
  return <details className="inspector panel">
    <summary><span><Terminal size={16} />Under the hood</span><span className="mono">Request / response / Python</span></summary>
    <Tabs value={tab} onChange={(value) => { setTab(value); setCopied(false); setCopyError(false); }}>
      <div className="inspector-toolbar"><Tabs.List><Tabs.Tab value="request">Request</Tabs.Tab><Tabs.Tab value="response">Response</Tabs.Tab><Tabs.Tab value="python">Python</Tabs.Tab></Tabs.List><Button variant="subtle" color="gray" size="xs" leftSection={copied ? <Check size={13} /> : <Copy size={13} />} onClick={() => void copy()}>{copied ? 'Copied' : 'Copy'}</Button></div>
      {copyError && <p className="copy-error" role="alert">Clipboard access is unavailable. Select the code below to copy it.</p>}
      <div className="code-view"><pre tabIndex={0} aria-label={`${tab ?? 'request'} code`}><code>{content}</code></pre></div>
    </Tabs>
    <div className="inspector-footer"><span className="mono">{evaluation?.response.model ?? model}</span>{evaluation ? <span>{seconds(evaluation.elapsed_ms)} round trip · {evaluation.response.usage.input_tokens} input / {evaluation.response.usage.output_tokens} output tokens · est. {dollars(evaluation.estimated_cost_usd)}</span> : <span>3 primitives · 1 API request</span>}</div>
  </details>;
}

/** Explain the typed outputs without crowding the main demonstration. */
export function PrimitiveGuide({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  return <Modal opened={opened} onClose={onClose} title="Three outputs. One decision layer." centered size="lg" closeButtonProps={{ 'aria-label': 'Close output guide' }} classNames={{ title: 'guide-title' }}>
    <p className="guide-intro">Jev turns text into typed outputs your Python application can act on. Each ticket needs one request for all three signals.</p>
    <div className="guide-item"><h3><span className="primitive-dot choice-dot" />Choice → owning team</h3><p>Select a category and inspect its full probability distribution. Uncertain ownership can go to a reviewer.</p></div>
    <div className="guide-item"><h3><span className="primitive-dot score-dot" />Score → customer impact</h3><p>Evaluate severity against an ordered rubric, from informational to critical. Inspect the probability at every level.</p></div>
    <div className="guide-item"><h3><span className="primitive-dot noul-dot" />Noul → active outage</h3><p>Return a value from 0 to 1 representing the probability of “yes.” Your code sets the escalation cutoff.</p></div>
    <p className="guide-callout">Confidence describes the output distribution, not measured accuracy. Routing reasons come from deterministic Python policy.</p>
    <Button component="a" href="https://docs.typesafe.ai/" target="_blank" rel="noreferrer" rightSection={<ArrowUpRight size={15} />} variant="light" fullWidth>Read the API documentation</Button>
  </Modal>;
}
