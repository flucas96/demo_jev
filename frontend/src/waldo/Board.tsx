import { useEffect, useRef, useState } from 'react';
import type { KeyboardEvent, MouseEvent } from 'react';
import { Check, Cpu, Crosshair, MousePointer2, SkipForward, X } from 'lucide-react';
import type { Point, Player, Puzzle } from './types';
import { boxStyle } from './geometry';
import Accuracy from './Accuracy';

interface Props {
  who: 'human' | 'jev'; player?: Player; preview?: Puzzle; active: boolean; started: boolean;
  modelError: boolean; onPick: (point: Point, round: number) => void; onSkip: () => void;
}

/** Let the human click the target while showing Jev's actual returned rectangle. */
export default function Board({ who, player, preview, active, started, modelError, onPick, onSkip }: Props) {
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
  return <section className={`waldo-board ${who} ${feedback ? feedback.correct ? 'hit' : 'miss' : ''}`} aria-label={human ? 'Dein Spielfeld' : 'Jevs Spielfeld'}>
    <div className="board-heading">
      <span className="player-icon">{human ? <MousePointer2 size={19} /> : <Cpu size={20} />}</span>
      <div><h2>{human ? 'Du' : 'Jev'}</h2><span>{human ? 'Menschliche Intuition' : 'Visuelle Intelligenz'}</span></div>
      <div className="board-score" aria-label={`${human ? 'Deine' : 'Jevs'} Punkte`}>{player?.score ?? 0}<small>Punkte</small></div>
    </div>
    <div className={`board-media ${!started ? 'waiting' : ''}`}>
      {picture && <div className={`board-picture ${selectable ? 'selectable' : ''}`} style={{ aspectRatio: `${picture.width} / ${picture.height}`, maxWidth: `calc(var(--board-height) * ${picture.width / picture.height})` }}
        tabIndex={human && active ? 0 : -1} role={human ? 'group' : undefined}
        aria-label={human ? 'Waldo anklicken. Tastatur: Pfeiltasten bewegen den Zielpunkt, Enter bestätigt.' : undefined}
        onClick={event => pick(point(event))} onKeyDown={keyboard}>
        <img src={picture.url} alt="Wimmelbild: Finde Waldo mit rot-weißem Streifenshirt und Brille" draggable={false} />
        {human && started && selectedPoint && <span className={`click-target ${feedback ? feedback.correct ? 'correct' : 'incorrect' : ''}`} style={{ left: `${selectedPoint.x * 100}%`, top: `${selectedPoint.y * 100}%` }} aria-hidden="true">{feedback ? feedback.correct ? <Check size={15} /> : <X size={15} /> : <Crosshair size={19} />}</span>}
        {started && feedback?.scoring_box && <div className={`answer-padding ${feedback.correct ? 'correct' : 'incorrect'}`} style={boxStyle(feedback.scoring_box)} aria-hidden="true" />}
        {started && box && <div className={`selection-box ${feedback ? feedback.correct ? 'correct' : 'incorrect' : 'drawing'}`} style={boxStyle(box)}>
          <i /><i /><i /><i />
          {feedback && <span className="box-label">{feedback.correct ? <Check size={11} /> : <X size={11} />}{feedback.confidence != null ? `${Math.round(feedback.confidence * 100)}%` : feedback.correct ? '+1' : '−1'}</span>}
        </div>}
      </div>}
      {!started && <div className="board-idle"><Crosshair size={30} strokeWidth={1.2} /><span>{human ? 'Dein Blick zählt.' : 'Eine Frage. Eine Box.'}</span></div>}
      {feedback && <div className={`board-toast ${feedback.correct ? 'good' : 'bad'}`} role="status">{feedback.correct ? <Check size={15} /> : <X size={15} />}{feedback.correct ? 'Gefunden' : feedback.skipped ? 'Übersprungen' : 'Daneben'}<strong>{feedback.correct ? '+1' : '−1'}</strong></div>}
    </div>
    <div className="board-bottom">
      <span title={started ? `Runde ${1 + (player?.round ?? 0)}` : undefined}>{started ? picture?.title ?? '—' : 'Bereit'}<i /><Accuracy player={player} /></span>
      {human ? <button type="button" onClick={onSkip} disabled={!selectable} title="Nächstes Bild, −1 Punkt"><SkipForward size={14} />Weiter <small>−1</small></button>
        : <span className={`jev-status ${active && !feedback && !modelError ? 'thinking' : ''}`}><b />{modelError ? 'Pausiert' : feedback?.elapsed_ms != null ? `${Math.round(feedback.elapsed_ms)} ms` : active ? 'Sucht …' : started ? 'Beendet' : 'Jev 1.14 · Box'}</span>}
    </div>
  </section>;
}
