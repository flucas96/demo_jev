import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, ArrowRight, Check, Flag, Play, RotateCcw, Trophy, X } from 'lucide-react';
import { Arena, DurationPicker, GameClock, GameMetrics, GameNotice, ModelPicker } from './GameElements';
import Leaderboard from './Leaderboard';
import BenchmarkCharts from './BenchmarkCharts';
import ModelIdentity, { ModelIcon } from './ModelIdentity';
import type { MatchState } from './types';
import useWaldoGame, { JEV } from './useWaldoGame';
import './waldo.css';
import './presentation.css';

/** A guided arcade flow uses the same live engine, then reveals the final standings. */
export default function WaldoPresentation() {
  const game = useWaldoGame();
  const [entered, setEntered] = useState(false);
  const [allRuns, setAllRuns] = useState(false);
  const [firstRound, setFirstRound] = useState<MatchState | null>(null);
  const intro = useRef<HTMLElement>(null);
  const arena = useRef<HTMLElement>(null);
  const handoff = useRef<HTMLElement>(null);
  const finish = useRef<HTMLElement>(null);
  const complete = game.phase === 'done' && game.match?.status === 'completed';
  const changingRival = complete && game.paired && game.comparison?.next_stage === 2;
  const finished = complete && (!game.paired || game.comparison?.next_stage === 3);
  const round = game.match?.stage ?? game.nextStage;
  const secondStage = round === 2 && !changingRival;
  const progress = game.match ? game.match.remaining_ms / (game.match.duration * 1000) : 1;
  const reduced = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  useEffect(() => {
    if (entered && (game.phase === 'idle' || game.phase === 'loading')) arena.current?.scrollIntoView({ behavior: reduced() ? 'instant' : 'smooth', block: 'start' });
  }, [entered, game.phase]);

  useEffect(() => {
    if (!changingRival) return;
    setFirstRound(game.match);
    handoff.current?.scrollIntoView({ behavior: reduced() ? 'instant' : 'smooth', block: 'start' });
  }, [changingRival, game.match]);

  useEffect(() => {
    if (finished) finish.current?.scrollIntoView({ behavior: reduced() ? 'instant' : 'smooth', block: 'start' });
  }, [finished]);

  function enter() { setEntered(true); setAllRuns(false); }
  function replay() { setFirstRound(null); game.reset(); setEntered(false); setAllRuns(false); intro.current?.scrollIntoView({ behavior: reduced() ? 'instant' : 'smooth' }); }

  const gameSection = <main className="presentation-game" ref={arena}>
      <div className="presentation-round-heading"><div><p className="presentation-eyebrow">ROUND {String(round).padStart(2, '0')} {game.paired ? '/ 02' : ''}</p><h2>You vs. <ModelIdentity model={game.currentModel} label={game.currentLabel} size={36} /></h2></div><GameClock game={game} />{game.phase === 'idle' ? <button type="button" className="arcade-start" onClick={() => void game.startGame()} disabled={!game.canStart}><Play size={20} fill="currentColor" />Start round {round}</button> : <button type="button" className="presentation-stop" onClick={game.stop} disabled={!game.active}><Flag size={15} />End round</button>}</div>
      <div className="match-progress"><span style={{ transform: `scaleX(${progress})` }} /></div>
      <GameNotice game={game} /><Arena game={game} />
      <div className="waldo-underboard"><span>Click Waldo. Beat the clock.</span><span><Check size={13} />+1 <X size={13} />−1</span></div>
      <GameMetrics metrics={game.match?.metrics} />
      {game.phase === 'done' && !complete && <div className="presentation-retry"><p>Round stopped. Your result is saved.</p><button className="arcade-start" onClick={() => void game.startGame()} disabled={!game.canStart}><RotateCcw size={18} />Retry round</button><button className="presentation-text-button" onClick={replay}>Back to setup</button></div>}
    </main>;

  return <div className="er-page waldo-page presentation-page">
    <header className="presentation-header"><a href="/" aria-label="Eraneos demo home"><img src="/brand/eraneos.svg" alt="Eraneos" /></a><a href="/waldo" aria-label="Return to playground"><ArrowLeft size={15} />Playground</a></header>
    <section className="presentation-intro" ref={intro}>
      <div className="intro-copy"><h1>Find Waldo.</h1>
        <div className="intro-rivals"><span><b>01</b><ModelIdentity model={game.model} label={game.selected?.label ?? 'Claude Opus 5.5'} size={31} /></span>{game.paired && <><ArrowRight size={22} /><span><b>02</b><ModelIdentity model={JEV} label="Jev" size={31} /></span></>}</div>
        <div className="presentation-setup"><ModelPicker game={game} /><div className="intro-duration"><span>Time per round</span><DurationPicker game={game} /></div></div>
        <GameNotice game={game} />
        <button className="arcade-start" type="button" onClick={enter} disabled={!game.canStart || game.locked}><Play size={22} fill="currentColor" />{game.nextStage === 2 ? 'Resume round two' : 'Start the game'}<ArrowRight size={22} /></button>
        {game.pendingPair && !game.locked && <button className="presentation-text-button" type="button" onClick={game.reset}>Start a new match</button>}
        <div className="intro-rules"><span><Check size={15} />Find +1</span><span><X size={15} />Miss −1</span><span>Click Waldo to score.</span></div>
      </div>
      <div className="intro-target" aria-hidden="true"><div className="target-orbit" /><div className="target-crosshair"><i /><i /><i /><i /><img src="/brand/waldo.png" alt="" /></div><span>YOUR TARGET</span><strong>Waldo</strong><p>Red stripes. Round glasses.</p></div>
    </section>
    {entered && secondStage && firstRound && <section className="presentation-round-recap"><p className="presentation-eyebrow">ROUND ONE COMPLETE</p><ModelIdentity model={firstRound.metrics.model} label={firstRound.model_label} size={42} /><div><span>You <strong>{firstRound.players.human.score}</strong></span><i>:</i><span>AI <strong>{firstRound.players.jev.score}</strong></span></div></section>}
    {entered && !secondStage && gameSection}

    {(changingRival || secondStage) && <section className="presentation-handoff" ref={handoff} aria-live="polite"><p className="presentation-eyebrow">ROUND ONE COMPLETE</p><div className="handoff-logo"><ModelIcon model={JEV} size={92} /></div><h2>Now, <span>Jev.</span></h2><p>Same images. New rival.</p>{changingRival && <button type="button" className="arcade-start" onClick={() => void game.startGame()} disabled={!game.canStart || game.locked}><Play size={22} fill="currentColor" />Start round 2<ArrowRight size={22} /></button>}</section>}
    {entered && secondStage && gameSection}
    {finished && <section className="presentation-finish" ref={finish}>
      <div className="finish-heading"><span className="finish-trophy"><Trophy size={38} /></span><p className="presentation-eyebrow">MATCH COMPLETE</p><h2>The final <span>score.</span></h2><p>You. Your models. Every point counts.</p></div>
      {game.historyError && <p role="alert">{game.historyError}</p>}
      <Leaderboard runs={game.runs} duration={Number(game.duration)} comparisonId={game.comparison?.id} onlyComparison={!allRuns && game.paired} />
      <BenchmarkCharts runs={game.runs} duration={Number(game.duration)} comparisonId={game.comparison?.id} onlyComparison={!allRuns && game.paired} />
      <div className="finish-actions"><button className="arcade-start" onClick={replay}><RotateCcw size={18} />Play again</button><button className="presentation-text-button" onClick={() => setAllRuns(value => !value)}>{allRuns ? 'This match only' : 'All runs'}</button></div>
      <p className="presentation-footnote">Same images and time limit. Round two may benefit from familiarity. * Partial cost.</p>
    </section>}
  </div>;
}
