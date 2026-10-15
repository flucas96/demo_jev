import { useState } from 'react';
import { ArrowUpLeft } from 'lucide-react';
import { dollars } from '../api';
import ModelIdentity, { ModelIcon } from './ModelIdentity';
import FullModelBenchmarks from './FullModelBenchmarks';
import MetricPicker, { metricValue } from './ChartMetric';
import type { ChartMetric } from './ChartMetric';
import type { Run } from './types';

interface Dot { run: Run; x: number; y: number }

/** Plot actual completed runs; hover or focus any logo to inspect the measurement. */
function Scatter({ runs, measure, metric }: { runs: Run[]; measure: 'time' | 'cost'; metric: ChartMetric }) {
  const [selected, setSelected] = useState<string | null>(null);
  const dots: Dot[] = runs.flatMap(run => {
    const x = measure === 'time' ? run.average_ms : run.cost_usd;
    const y = metricValue(run, metric);
    return x == null || y == null ? [] : [{ run, x, y }];
  });
  const metricLabel = metric === 'accuracy' ? 'Accuracy' : 'Score';
  const yMin = metric === 'accuracy' ? 0 : Math.min(0, ...runs.map(run => run.score));
  const yMax = metric === 'accuracy' ? 100 : yMin + Math.max(1, Math.ceil((Math.max(4, ...runs.map(run => run.score)) - yMin) / 4)) * 4;
  const max = Math.max(measure === 'time' ? 1000 : .001, ...dots.map(dot => dot.x));
  const magnitude = 10 ** Math.floor(Math.log10(max / 4));
  const xMax = Math.ceil(max * 1.1 / (4 * magnitude)) * 4 * magnitude;
  const active = dots.find(dot => dot.run.id === selected);
  const label = (value: number) => measure === 'time' ? Math.round(value).toLocaleString('en-US') : `$${value < .01 ? value.toFixed(4) : value.toFixed(3)}`;
  const ticks = [0, .25, .5, .75, 1];
  return <article className="benchmark-chart">
    <div className="chart-title"><div><span>{measure === 'time' ? 'SPEED' : 'SPEND'}</span><h3>{metricLabel} vs. {measure === 'time' ? 'response time' : 'cost'}</h3></div><ArrowUpLeft size={24} /></div>
    <div className="chart-axis-caption">{metric === 'accuracy' ? 'Accuracy' : 'Points'} ↑<span>Higher + further left is better</span></div>
    {!dots.length ? <div className="chart-empty">Finish a round to see your benchmark.</div> : <div className="scatter" role="group" aria-label={`${measure === 'time' ? 'Average response time' : 'Cost'} on x-axis, ${metric === 'accuracy' ? 'accuracy' : 'points'} on y-axis`}>
      <div className="scatter-y-labels">{ticks.map(t => <span key={t} style={{ bottom: `${t * 100}%` }}>{Math.round(yMin + (yMax - yMin) * t)}{metric === 'accuracy' ? '%' : ''}</span>)}</div>
      <div className="scatter-plot"><div className="chart-good-zone" />
        {ticks.map(t => <div className="chart-grid" key={t} style={{ bottom: `${t * 100}%` }} />)}
        {ticks.map(t => <span className="scatter-x-label" key={t} style={{ left: `${t * 100}%` }}>{label(xMax * t)}</span>)}
        {dots.map(dot => <button key={dot.run.id} className={`scatter-point ${selected === dot.run.id ? 'selected' : ''}`} style={{ left: `${dot.x / xMax * 100}%`, bottom: `${(dot.y - yMin) / (yMax - yMin) * 100}%` }} onMouseEnter={() => setSelected(dot.run.id)} onMouseLeave={() => setSelected(null)} onFocus={() => setSelected(dot.run.id)} onBlur={() => setSelected(null)} onClick={() => setSelected(dot.run.id)} aria-label={`${dot.run.label}: ${Math.round(dot.y)}${metric === 'accuracy' ? '% accuracy' : ' points'}, ${measure === 'time' ? `${Math.round(dot.x)} milliseconds` : `${dollars(dot.x)}${dot.run.cost_partial ? ', partial cost' : ''}`}`}><ModelIcon model={dot.run.model} size={21} /></button>)}
      </div><span className="scatter-x-title">{measure === 'time' ? 'Average response · ms' : 'Total model cost · USD'} →</span>
    </div>}
    <div className="chart-inspection" aria-live="polite">{active ? <><ModelIdentity model={active.run.model} label={active.run.label} size={16} /><strong>{Math.round(active.y)}{metric === 'accuracy' ? '%' : ' pts'}</strong><span>{measure === 'time' ? `${Math.round(active.x).toLocaleString('en-US')} ms` : `${dollars(active.x)}${active.run.cost_partial ? '*' : ''}`}</span></> : <span>{dots.length ? 'Hover or focus a logo to inspect its run.' : 'Live results only. No example points.'}</span>}</div>
  </article>;
}

/** Keep both plots on the same runs and score axis, with explicit comparison limits. */
export default function BenchmarkCharts({ runs, duration, comparisonId, onlyComparison = false }: { runs: Run[]; duration: number; comparisonId?: string; onlyComparison?: boolean }) {
  const [metric, setMetric] = useState<ChartMetric>('score');
  const completed = runs.filter(run => run.status === 'completed' && run.duration === duration && (!onlyComparison || run.comparison_id === comparisonId)).slice(0, 30);
  const models = [...new Map(completed.map(run => [run.model, run])).values()];
  return <section className="benchmark-charts" aria-label="Model benchmark charts"><div className="chart-metric-control"><MetricPicker value={metric} onChange={setMetric} /></div><div className="benchmark-chart-grid"><Scatter runs={completed} measure="time" metric={metric} /><Scatter runs={completed} measure="cost" metric={metric} /></div>
    {!!models.length && <div className="chart-legend">{models.map(run => <ModelIdentity key={run.model} model={run.model} label={run.label} size={18} />)}</div>}
    <p className="chart-footnote">Up to 30 completed {duration}s model runs. Human response time is not measured. * Partial cost; final charges may be higher.</p>
    <div className="full-benchmark-action"><FullModelBenchmarks /></div>
  </section>;
}
