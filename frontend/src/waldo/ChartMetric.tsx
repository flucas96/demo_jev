import { SegmentedControl } from '@mantine/core';
import type { Run } from './types';

export type ChartMetric = 'score' | 'accuracy';

/** Unknown accuracy stays absent instead of being plotted as a measured zero. */
export function metricValue(run: Run, metric: ChartMetric): number | null {
  const attempts = run.hits + run.misses;
  return metric === 'score' ? run.score : attempts ? run.hits / attempts * 100 : null;
}

/** Share the same vertical-axis switch across personal and full benchmark charts. */
export default function MetricPicker({ value, onChange }: { value: ChartMetric; onChange: (value: ChartMetric) => void }) {
  return <SegmentedControl aria-label="Chart vertical axis" value={value} onChange={value => onChange(value === 'accuracy' ? 'accuracy' : 'score')} data={[{value:'score', label:'Points'}, {value:'accuracy', label:'Accuracy'}]} size="sm" className="chart-metric-picker" />;
}
