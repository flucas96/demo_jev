import { useEffect, useRef, useState } from 'react';
import type { KeyboardEvent, MouseEvent } from 'react';
import { Check, Crosshair, SkipForward, X } from 'lucide-react';
import type { Point, Player, Puzzle } from './types';
import { boxStyle } from './geometry';
import Accuracy from './Accuracy';
import { ModelIcon } from './ModelIdentity';

interface Props {
  who: 'human' | 'jev'; player?: Player; preview?: Puzzle; active: boolean; started: boolean;
  modelError: boolean; modelLabel?: string; modelId?: string; onPick: (point: Point, round: number) => void; onSkip: () => void;
}

/** Let the human click the target while showing Jev's actual returned rectangle. */
export default function Board({ who, player, preview, active, started, modelError, modelLabel = 'Jev', modelId = 'jev-1.14.0', onPick, onSkip }: Props) {
  const [draft, setDraft] = useState<Point | null>(null);
  const pending = useRef(false);
  const picture = player?.puzzle ?? preview;
  const feedback = player?.feedback;
  const human = who === 'human';
  const selectable = human && active && !feedback;
  useEffect(() => { setDraft(null); pending.current = false; }, [player?.round, active, feedback]);

  function point(event: MouseEvent<HTMLDivElement>): Point {
    const rect = event.currentTarget.getBoundingClientRect();
    return { x: Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)), y: Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)) };
  }
  function pick(target: Point) {
    if (!selectable || pending.current) return;
    pending.current = true; setDraft(target); onPick(target, player?.round ?? -1);
  }
  function keyboard(event: KeyboardEvent<HTMLDivElement>) {
    if (!selectable || pending.current) return;
    if (event.key === 'Escape') { setDraft(null); return; }
    if (event.key === 'Enter' && draft) { event.preventDefault(); pick(draft); return; }
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
    event.preventDefault();
    const target = draft ?? { x: .5, y: .5 };
    const dx = event.key === 'ArrowLeft' ? -.01 : event.key === 'ArrowRight' ? .01 : 0;
    const dy = event.key === 'ArrowUp' ? -.01 : event.key === 'ArrowDown' ? .01 : 0;
    setDraft({ x: Math.max(0, Math.min(1, target.x + dx)), y: Math.max(0, Math.min(1, target.y + dy)) });
  }
  const box = feedback?.box;
  const selectedPoint = feedback?.point ?? draft;
  return <section className={`waldo-board ${who} ${feedback ? feedback.correct ? 'hit' : 'miss' : ''}`} aria-label={human ? 'Your board' : `${modelLabel}: board`}>
    <div className="board-heading">
      <span className="player-icon"><ModelIcon model={human ? 'human' : modelId} size={26} /></span>
      <div><h2>{human ? 'You' : modelLabel}</h2></div>
      <div className="board-score" aria-label={`${human ? 'Your' : modelLabel} points`}>{player?.score ?? 0}<small>points</small></div>
    </div>
    <div className={`board-media ${!started ? 'waiting' : ''}`}>
      {picture && <div className={`board-picture ${selectable ? 'selectable' : ''}`} style={{ aspectRatio: `${picture.width} / ${picture.height}`, maxWidth: `calc(var(--board-height) * ${picture.width / picture.height})` }}
        tabIndex={human && active ? 0 : -1} role={human ? 'group' : undefined}
        aria-label={human ? 'Click Waldo. Keyboard: arrow keys move your cursor; Enter confirms.' : undefined}
        onClick={event => pick(point(event))} onKeyDown={keyboard}>
        <img src={picture.url} alt="Find Waldo in red and white stripes with round glasses" draggable={false} />
        {human && started && selectedPoint && <span className={`click-target ${feedback ? feedback.correct ? 'correct' : 'incorrect' : ''}`} style={{ left: `${selectedPoint.x * 100}%`, top: `${selectedPoint.y * 100}%` }} aria-hidden="true">{feedback ? feedback.correct ? <Check size={15} /> : <X size={15} /> : <Crosshair size={19} />}</span>}
        {started && feedback?.scoring_box && <div className={`answer-padding ${feedback.correct ? 'correct' : 'incorrect'}`} style={boxStyle(feedback.scoring_box)} aria-hidden="true" />}
        {started && box && <div className={`selection-box ${feedback ? feedback.correct ? 'correct' : 'incorrect' : 'drawing'}`} style={boxStyle(box)}>
          <i /><i /><i /><i />
          {feedback && <span className="box-label">{feedback.correct ? <Check size={11} /> : <X size={11} />}{feedback.confidence != null ? `${Math.round(feedback.confidence * 100)}%` : feedback.correct ? '+1' : '−1'}</span>}
        </div>}
      </div>}
      {!started && <div className="board-idle"><Crosshair size={30} strokeWidth={1.2} /><span>{human ? 'Click to find him.' : 'One image. One answer.'}</span></div>}
      {feedback && <div className={`board-toast ${feedback.correct ? 'good' : 'bad'}`} role="status">{feedback.correct ? <Check size={15} /> : <X size={15} />}{feedback.correct ? 'Found' : feedback.skipped ? 'Skipped' : 'Miss'}<strong>{feedback.correct ? '+1' : '−1'}</strong></div>}
    </div>
    <div className="board-bottom">
      <span title={started ? `Image ${1 + (player?.round ?? 0)}` : undefined}>{started ? picture?.title ?? '—' : 'Ready'}<i /><Accuracy player={player} /></span>
      {human ? <button type="button" onClick={onSkip} disabled={!selectable} title="Next image, −1 point"><SkipForward size={14} />Skip <small>−1</small></button>
        : <span className={`jev-status ${active && !feedback && !modelError ? 'thinking' : ''}`}><b />{modelError ? 'Paused' : feedback?.elapsed_ms != null ? `${Math.round(feedback.elapsed_ms)} ms` : active ? 'Searching…' : started ? 'Finished' : 'Ready'}</span>}
    </div>
  </section>;
}
