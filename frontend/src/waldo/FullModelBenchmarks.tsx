import { useId, useState } from 'react';
import { Modal } from '@mantine/core';
import { ArrowUpLeft, ChartScatter, LoaderCircle } from 'lucide-react';
import { api, dollars } from '../api';
import ModelIdentity from './ModelIdentity';
import type { BenchmarkReport, Run } from './types';
import MetricPicker, { metricValue } from './ChartMetric';
import type { ChartMetric } from './ChartMetric';

const colors = ['#ff753e', '#a56ce0', '#268fac', '#c39a28', '#d25c8b', '#478b51', '#5b7fd5'];
const shortCost = (value: number) => `$${value < .01 ? value.toFixed(4) : value.toFixed(3)}`;

/** Keep true coordinates while separating model labels into a readable connected rail. */
function ModelChart({ runs, measure, metric }: { runs: Run[]; measure: 'time' | 'cost'; metric: ChartMetric }) {
  const [selected, setSelected] = useState<string | null>(null);
  const id = useId();
  const width = 1100, left = 55, right = 735, top = 30;
  const plotHeight = Math.max(350, runs.length * 30);
  const bottom = top + plotHeight;
  const metricLabel = metric === 'accuracy' ? 'Accuracy' : 'Score';
  const minScore = metric === 'accuracy' ? 0 : Math.min(0, ...runs.map(run => run.score));
  const maxScore = metric === 'accuracy' ? 100 : Math.max(4, ...runs.map(run => run.score));
  const magnitude = 10 ** Math.floor(Math.log10((maxScore - minScore) / 4));
  const scoreStep = metric === 'accuracy' ? 25 : Math.ceil((maxScore - minScore) / (4 * magnitude)) * magnitude;
  const yMin = Math.floor(minScore / scoreStep) * scoreStep;
  const yMax = Math.ceil(maxScore / scoreStep) * scoreStep;
  const scoreTicks = Array.from({length: Math.round((yMax - yMin) / scoreStep) + 1}, (_, index) => yMin + index * scoreStep);
  const measured = runs.flatMap((run, index) => {
    const value = measure === 'time' ? run.average_ms : run.cost_usd;
    const score = metricValue(run, metric);
    return value == null || score == null ? [] : [{ run, value, score, index }];
  });
  const max = Math.max(measure === 'time' ? 1000 : .001, ...measured.map(dot => dot.value));
  const step = 10 ** Math.floor(Math.log10(max / 4));
  const xMax = Math.ceil(max * 1.08 / (4 * step)) * 4 * step;
  const dots = measured.map(dot => ({ ...dot, x: left + dot.value / xMax * (right - left), y: bottom - (dot.score - yMin) / (yMax - yMin) * plotHeight, labelY: 0 }))
    .sort((a, b) => a.y - b.y || a.index - b.index);
  let nextLabelY = top;
  for (const dot of dots) { dot.labelY = Math.max(dot.y, nextLabelY); nextLabelY = dot.labelY + 30; }
  nextLabelY = bottom;
  for (const dot of [...dots].reverse()) { dot.labelY = Math.min(dot.labelY, nextLabelY); nextLabelY = dot.labelY - 30; }
  const ticks = [0, .25, .5, .75, 1];
  const active = dots.find(dot => dot.run.model === selected);
  return <article className="full-model-chart">
    <header><div><span>{measure === 'time' ? 'SPEED' : 'COST'}</span><h3>{metricLabel} vs. {measure === 'time' ? 'response time' : 'cost'}</h3></div><span><ArrowUpLeft size={19} />Higher + further left is better</span></header>
    <div className="full-chart-scroll"><svg viewBox={`0 0 ${width} ${bottom + 65}`} role="group" aria-labelledby={id}>
      <title id={id}>{measure === 'time' ? 'Response time' : 'Cost'} on the horizontal axis, {metric === 'accuracy' ? 'accuracy' : 'points'} on the vertical axis. One measured point per model.</title>
      <text x="4" y="14" className="full-axis-title">{metric === 'accuracy' ? 'Accuracy' : 'Points'} ↑</text>
      {scoreTicks.map(score => <g key={score}><line className="full-grid" x1={left} x2={right} y1={bottom - (score - yMin) / (yMax - yMin) * plotHeight} y2={bottom - (score - yMin) / (yMax - yMin) * plotHeight} /><text className="full-axis-tick" x={left - 14} y={bottom - (score - yMin) / (yMax - yMin) * plotHeight + 4} textAnchor="end">{score}{metric === 'accuracy' ? '%' : ''}</text></g>)}
      {ticks.map(t => <text key={t} className="full-axis-tick" x={left + t * (right - left)} y={bottom + 27} textAnchor="middle">{measure === 'time' ? Math.round(xMax * t).toLocaleString('en-US') : shortCost(xMax * t)}</text>)}
      <text className="full-axis-title" x={(left + right) / 2} y={bottom + 57} textAnchor="middle">{measure === 'time' ? 'Average response · ms' : 'Total model cost · USD'} →</text>
      {dots.map(dot => <g key={dot.run.model} className={`model-plot-item ${selected && selected !== dot.run.model ? 'muted' : ''} ${selected === dot.run.model ? 'active' : ''}`} role="button" tabIndex={0} aria-label={`${dot.run.label}: ${Math.round(dot.score)}${metric === 'accuracy' ? '% accuracy' : ' points'}, ${measure === 'time' ? `${Math.round(dot.value)} milliseconds` : dollars(dot.value)}`} onMouseEnter={() => setSelected(dot.run.model)} onMouseLeave={() => setSelected(null)} onFocus={() => setSelected(dot.run.model)} onBlur={() => setSelected(null)} onClick={() => setSelected(dot.run.model)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelected(dot.run.model); } }}>
        <path d={`M ${dot.x} ${dot.y} L ${right + 20} ${dot.y} L ${right + 42} ${dot.labelY} L ${right + 55} ${dot.labelY}`} fill="none" stroke={colors[dot.index % colors.length]} className="model-leader" />
        <circle cx={dot.x} cy={dot.y} r="12" fill={colors[dot.index % colors.length]} className="model-marker" /><text x={dot.x} y={dot.y + 4} textAnchor="middle" className="model-number">{dot.index + 1}</text>
        <foreignObject x={right + 62} y={dot.labelY - 14} width="290" height="30"><div className="full-model-label"><span>{dot.index + 1}</span><ModelIdentity model={dot.run.model} label={dot.run.label} size={18} /></div></foreignObject>
      </g>)}
    </svg></div>
    <div className="full-model-inspection" aria-live="polite">{active ? <><ModelIdentity model={active.run.model} label={active.run.label} /><b>{Math.round(active.score)}{metric === 'accuracy' ? '% accuracy' : ' points'}</b><span>{measure === 'time' ? `${Math.round(active.value).toLocaleString('en-US')} ms` : dollars(active.value)}</span></> : 'Select a model label or point to highlight its measurement.'}</div>
  </article>;
}

/** Open saved real benchmarks on demand; this control never starts paid model calls. */
export default function FullModelBenchmarks() {
  const [opened, setOpened] = useState(false);
  const [report, setReport] = useState<BenchmarkReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [metric, setMetric] = useState<ChartMetric>('score');
  async function show() {
    setOpened(true); setLoading(true); setError(null);
    try { setReport(await api<BenchmarkReport | null>('/api/waldo/benchmarks')); }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'Could not load benchmarks.'); }
    finally { setLoading(false); }
  }
  const results = [...(report?.results ?? [])].sort((a, b) => Number(b.status === 'completed') - Number(a.status === 'completed') || (b.run?.score ?? 0) - (a.run?.score ?? 0));
  const runs = results.flatMap(result => result.status === 'completed' && result.run ? [result.run] : []);
  return <>
    <button type="button" className="full-benchmark-button" onClick={() => void show()}><ChartScatter size={18} />Show full model benchmarks</button>
    <Modal opened={opened} onClose={() => setOpened(false)} title="Full model benchmarks" closeButtonProps={{'aria-label':'Close full model benchmarks'}} size="min(1280px, 96vw)" centered withinPortal={false} className="full-benchmark-modal">
      {loading ? <div className="full-benchmark-loading" role="status"><LoaderCircle size={24} />Loading measurements…</div> : error ? <p role="alert">{error}</p> : !report ? <p>No benchmark has been measured yet.</p> : <>
        {!!runs.length && <><div className="chart-metric-control"><MetricPicker value={metric} onChange={setMetric} /></div><ModelChart runs={runs} measure="time" metric={metric} /><ModelChart runs={runs} measure="cost" metric={metric} /></>}
        <div className="full-benchmark-table"><table><thead><tr><th>#</th><th>Model</th><th>Points</th><th>Accuracy</th><th>Avg. response</th><th>Cost</th><th>Calls</th></tr></thead><tbody>{results.map((result, index) => {
          const run = result.run, done = result.status === 'completed' && run;
          return <tr key={result.model}><td>{done ? index + 1 : '—'}</td><td><ModelIdentity model={result.model} label={result.label} size={22} />{!done && <small>{result.error ?? 'Measurement in progress'}</small>}</td><td>{done ? run.score : '—'}</td><td>{done && run.hits + run.misses ? `${Math.round(run.hits / (run.hits + run.misses) * 100)}%` : '—'}</td><td>{done && run.average_ms != null ? `${Math.round(run.average_ms).toLocaleString('en-US')} ms` : '—'}</td><td>{run ? `${dollars(run.cost_usd)}${run.cost_partial ? '*' : ''}` : '—'}</td><td>{run?.calls ?? '—'}</td></tr>;
        })}</tbody></table></div>
        <p className="full-benchmark-method">Single-run snapshot, not a general model ranking. Late answers earn no points; their returned usage is included in cost and response time. * Partial cost.</p>
      </>}
    </Modal>
  </>;
}
