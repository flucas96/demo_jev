import { useEffect, useState } from 'react';
import { Alert, Modal, Tooltip } from '@mantine/core';
import { ArrowRight, Check, CircleHelp, Flag, MonitorPlay, Play, Trophy, X } from 'lucide-react';
import { dollars } from '../api';
import BrandHeader from '../brand/BrandHeader';
import Accuracy from './Accuracy';
import Leaderboard from './Leaderboard';
import BenchmarkCharts from './BenchmarkCharts';
import ModelIdentity from './ModelIdentity';
import { Arena, DurationPicker, GameClock, GameMetrics, GameNotice, ModelPicker } from './GameElements';
import useWaldoGame from './useWaldoGame';
import './waldo.css';

/** The compact playground shares every game rule with presentation mode. */
export default function WaldoGame() {
  const game = useWaldoGame(false);
  const [rules, setRules] = useState(false);
  const [summary, setSummary] = useState(false);
  useEffect(() => { setSummary(game.phase === 'done'); }, [game.phase]);
  const { match, comparison, runs, nextStage, paired, currentLabel, currentModel } = game;
  const completed = runs.filter(run => run.status === 'completed');
  const humanWins = completed.filter(run => run.human_score > run.score).length;
  const aiWins = completed.filter(run => run.score > run.human_score).length;
  const progress = match ? match.remaining_ms / (match.duration * 1000) : 1;
  const startLabel = game.phase === 'loading' ? 'Preparing' : game.phase === 'countdown' ? 'Get ready' : paired && nextStage === 2 ? 'Continue with Jev' : 'Start match';
  const resultTitle = match?.status !== 'completed' ? 'Run saved.' : match?.winner === 'human' ? 'You win.' : match?.winner === 'jev' ? `${currentLabel} wins.` : 'A draw.';

  return <div className="er-page waldo-page">
    <BrandHeader game />
    <main className="waldo-main">
      <div className="waldo-intro"><div><p className="er-kicker"><span />Human vs. AI</p><h1>Spot on<span>.</span></h1><p className="waldo-subtitle">Same images. Who finds Waldo first?</p></div>
        <div className="waldo-target"><img src="/api/waldo/images/target?v=3" alt="Find Waldo" /><div><span>FIND</span><strong>Waldo</strong><small>Click to score.</small></div></div>
        <Tooltip label={`${completed.length} completed rounds saved on this server`}><div className="match-total"><Trophy size={15} /><span>Overall wins</span><strong>You {humanWins}<i>:</i>{aiWins} AI</strong></div></Tooltip>
      </div>
      <div className="benchmark-setup"><ModelPicker game={game} />

        <a href="/waldo/presentation" className="presentation-link"><MonitorPlay size={16} />Presentation</a>
        {comparison && !game.locked && <button type="button" className="benchmark-reset" onClick={game.reset}>New match</button>}
      </div>
      <div className="waldo-controls"><div className="waldo-config"><DurationPicker game={game} /><span className="per-round">per round</span><button type="button" className="waldo-help" onClick={() => setRules(true)} aria-label="Game rules"><CircleHelp size={18} /></button></div><GameClock game={game} />
        {game.active ? <button type="button" className="er-button secondary" onClick={game.stop}><Flag size={15} />End round</button> : <button type="button" className="er-button" disabled={game.locked || !game.canStart} onClick={() => void game.startGame()}><Play size={15} fill="currentColor" />{startLabel}</button>}
      </div>
      <div className="match-progress" aria-hidden="true"><span style={{ transform: `scaleX(${progress})` }} /></div>
      <GameNotice game={game} /><Arena game={game} />
      <div className="waldo-underboard"><span><Check size={13} />Hit +1 <i /><X size={13} />Miss −1</span><span>AI: one attempt per image</span></div>
      <GameMetrics metrics={match?.metrics} />
      <div className="waldo-measure-note">{game.phase === 'done' && <button onClick={() => setSummary(true)} type="button">View result <ArrowRight size={13} /></button>}<ModelIdentity model={currentModel} label={currentModel} size={13} /></div>
      {game.historyError && <Alert color="orange">{game.historyError}</Alert>}
      <Leaderboard runs={runs} duration={Number(game.duration) || 60} comparisonId={comparison?.id} />
      <BenchmarkCharts runs={runs} duration={Number(game.duration) || 60} />
    </main>
    <footer className="er-footer"><span>Eraneos AI playground</span><button type="button" className="waldo-credit-button" onClick={() => setRules(true)}>Rules & credits</button></footer>
    <Modal opened={rules} onClose={() => setRules(false)} title="One match. Two rounds." centered size="lg" className="waldo-modal">
      <div className="waldo-rules"><p>Choose any model for a single round. You can switch models at any time; an unfinished run remains in the history without a rank. Presentation mode guides you through an LLM round followed automatically by Jev, using the same images and time limit.</p>
        <p>Click Waldo. Hit +1, miss −1. AI gets one attempt per image; a miss immediately changes the picture. A correct box stays visible for 0.45 seconds. Your image changes after a hit, a skip, or three misses.</p>
        <p>Your click counts inside the body plus a 20% margin. Model boxes receive 30% padding for the head check: they must cover at least 50% of the head, and 55% of the raw box must fall inside the body with its 20% margin. Confidence does not change points.</p>
        <p>The server owns the clock and scores. Late answers earn no points. Stopped or failed runs remain in the leaderboard without a rank. Costs marked * may exclude pending or failed requests.</p>
        <p>Your second round can benefit from recognizing the scenes. Caching affects latency and cost. Different matches use different image orders; rankings compare equal time limits. This game is not a general model benchmark.</p>
        <details><summary>Requests & billing</summary><p>Every model receives the same unmarked JPEGs, with no position hints. Jev uses its native box question. Gateway models receive the same task plus a JSON coordinate format, with a 256-token output limit.</p><p>Gateway-reported costs include cache charges. Otherwise, estimates use reported input/output tokens and the supplied October 15, 2026 catalogue prices. Jev is estimated at $0.042 per million input tokens; output is free.</p></details>
        <p>Keyboard: arrow keys move your cursor; Enter confirms. Results are stored locally on this server.</p><p className="waldo-credit">Illustrations generated with Imagegen and placed characters. Waldo / Wally: Martin Handford. This is an unofficial demo. Provider marks identify the models; they do not imply endorsement.</p>
      </div>
    </Modal>
    <Modal opened={summary} onClose={() => setSummary(false)} centered title={paired ? `ROUND ${match?.stage ?? 1} OF 2` : 'RESULT'} size="lg" className="waldo-modal result-modal">
      <div className="waldo-result"><span className="result-trophy"><Trophy size={28} /></span><h2>{resultTitle}</h2><div className="result-score"><div><ModelIdentity model="human" label="You" /><strong>{match?.players.human.score ?? 0}</strong><Accuracy player={match?.players.human} /></div><i>:</i><div><ModelIdentity model={currentModel} label={currentLabel} /><strong>{match?.players.jev.score ?? 0}</strong><Accuracy player={match?.players.jev} /></div></div>
        <p>{match?.status === 'completed' ? `${match.duration} seconds · saved to the leaderboard` : 'Incomplete run · saved without a rank'}</p>
        <div className="result-metrics"><span>{match?.metrics.calls ?? 0} calls</span><span>{match?.metrics.average_ms != null ? `${Math.round(match.metrics.average_ms)} ms avg.` : '—'}</span><span>{dollars(match?.metrics.cost_usd)}{match?.metrics.cost_partial ? '*' : ''}</span></div>
        <button className="er-button" type="button" onClick={() => { game.reset(); setSummary(false); document.querySelector<HTMLInputElement>('[aria-label="Opponent model"]')?.focus(); }}><ArrowRight size={15} />Choose another model</button><button className="result-dismiss" type="button" onClick={() => setSummary(false)}>View leaderboard</button>
      </div>
    </Modal>
  </div>;
}
