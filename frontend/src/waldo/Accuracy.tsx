import type { Player } from './types';

/** Report scored attempts only; transport errors and unfinished calls are not wrong answers. */
export default function Accuracy({ player }: { player?: Player }) {
  const attempts = (player?.hits ?? 0) + (player?.misses ?? 0);
  const percentage = attempts ? Math.round((player?.hits ?? 0) / attempts * 100) : null;
  return <span className="waldo-accuracy" title={`${player?.hits ?? 0} von ${attempts} gewerteten Versuchen richtig. Überspringen zählt als Fehler.`}>
    <span className="accuracy-track" aria-hidden="true"><i style={{ width: `${percentage ?? 0}%` }} /></span>
    <b>{percentage === null ? '—' : `${percentage}%`}</b> Trefferquote
  </span>;
}
