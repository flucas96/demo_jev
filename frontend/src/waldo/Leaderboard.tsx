import { Trophy } from 'lucide-react';
import { dollars } from '../api';
import ModelIdentity from './ModelIdentity';
import type { Run } from './types';

const statusLabels = { completed: 'Finished', stopped: 'Stopped', error: 'API error', disconnected: 'Disconnected' };

/** Give every competitor a row; rank only completed runs with the same time limit. */
export default function Leaderboard({ runs, duration, comparisonId, onlyComparison = false }: { runs: Run[]; duration: number; comparisonId?: string; onlyComparison?: boolean }) {
  const filtered = runs.filter(run => run.duration === duration && (!onlyComparison || run.comparison_id === comparisonId));
  const rows = filtered.flatMap(run => [
    { run, human: false, score: run.score, hits: run.hits, misses: run.misses },
    { run, human: true, score: run.human_score, hits: run.human_hits, misses: run.human_misses },
  ]).sort((a, b) => Number(b.run.status === 'completed') - Number(a.run.status === 'completed') || b.score - a.score ||
    b.hits / Math.max(1, b.hits + b.misses) - a.hits / Math.max(1, a.hits + a.misses) || a.run.created_at.localeCompare(b.run.created_at));
  return <section className="waldo-leaderboard" aria-label="Leaderboard">
    <div className="leaderboard-heading"><div><Trophy size={19} /><h2>Leaderboard</h2><span>{duration}s rounds</span></div><small>{filtered.length} runs · saved locally</small></div>
    {!rows.length ? <div className="leaderboard-empty">Your first match starts above.</div> : <div className="leaderboard-scroll"><table>
      <thead><tr><th>#</th><th>Player</th><th>Score</th><th>Accuracy</th><th>Avg. response</th><th>Cost</th><th>Run</th></tr></thead>
      <tbody>{rows.map(({ run, human, score, hits, misses }, index) => <tr key={`${run.id}-${human}`} className={`${run.comparison_id && run.comparison_id === comparisonId ? 'current-comparison' : ''} ${run.status !== 'completed' ? 'unranked' : ''}`}>
        <td className="leaderboard-rank">{run.status === 'completed' ? index + 1 : '—'}</td>
        <td><strong><ModelIdentity model={human ? 'human' : run.model} label={human ? 'You' : run.label} size={25} /></strong><small>{human ? <>vs. <ModelIdentity model={run.model} label={run.label} size={13} /></> : `${run.calls} calls`}{run.comparison_id ? ` · Round ${run.stage}` : ' · Solo'}</small></td>
        <td className="leaderboard-score"><b>{score}</b></td>
        <td><div className="leaderboard-accuracy"><span><i style={{ width: `${hits / Math.max(1, hits + misses) * 100}%` }} /></span>{hits + misses ? `${Math.round(hits / (hits + misses) * 100)}%` : '—'}</div></td>
        <td>{human || run.average_ms == null ? '—' : `${Math.round(run.average_ms).toLocaleString('en-US')} ms`}</td>
        <td title={human ? 'No API cost for human play.' : run.cost_basis === 'gateway' ? 'Gateway-reported cost, including cache charges.' : 'Estimate from reported tokens; caching and tariffs can differ.'}>
          {human ? '$0.00' : dollars(run.cost_usd)}{!human && run.cost_partial ? '*' : ''}<small>{human ? 'no API calls' : run.cost_basis === 'gateway' ? 'gateway' : run.cost_basis === 'estimate' ? '' : run.cost_basis === 'mixed' ? '' : 'unavailable'}</small>
        </td>
        <td><time dateTime={run.created_at}>{new Date(run.created_at).toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}</time>{run.status !== 'completed' && <small className="run-status">{statusLabels[run.status]}</small>}</td>
      </tr>)}</tbody>
    </table></div>}
    {!!rows.length && <p className="leaderboard-note">Ranked by score, then accuracy. * Partial cost. Human response time is not measured.</p>}
  </section>;
}
