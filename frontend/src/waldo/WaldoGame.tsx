import { useEffect, useRef, useState } from 'react';
import { Alert, Modal, NumberInput, Tooltip } from '@mantine/core';
import { Activity, ArrowRight, Check, CircleHelp, Clock3, Coins, Flag, Hash, LoaderCircle, Play, RotateCcw, Trophy, X } from 'lucide-react';
import { api, dollars } from '../api';
import BrandHeader from '../brand/BrandHeader';
import Board from './Board';
import Accuracy from './Accuracy';
import type { Point, Catalog, MatchState, Totals } from './types';
import './waldo.css';

const emptyTotals: Totals = { human: 0, jev: 0, draw: 0, games: 0 };
const storageKey = 'eraneos-waldo-matches-v1';

/** Read optional browser-local results without making storage a requirement to play. */
function readTotals(): Totals {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(storageKey) ?? 'null');
    if (value && typeof value === 'object' && ['human', 'jev', 'draw', 'games'].every(key => key in value && typeof (value as Record<string, unknown>)[key] === 'number')) return value as Totals;
  } catch { /* Private browser storage can be unavailable. */ }
  return emptyTotals;
}

/** Show measured call durations without inventing smooth or precomputed data. */
function LatencyTrace({ values }: { values: number[] }) {
  if (!values.length) return <div className="latency-placeholder" aria-hidden="true"><i /><i /><i /><i /><i /><i /><i /><i /></div>;
  const max = Math.max(...values, 1);
  const points = values.map((value, index) => `${4 + index * 112 / Math.max(values.length-1, 1)},${32 - value / max * 26}`).join(' ');
  return <svg className="latency-trace" viewBox="0 0 120 36" role="img" aria-label="Verlauf der letzten gemessenen API-Antwortzeiten"><polyline points={points} fill="none" stroke="currentColor" strokeWidth="1.8" vectorEffect="non-scaling-stroke" />{values.length === 1 && <circle cx="4" cy="6" r="2" fill="currentColor" />}</svg>;
}

/** Run a timed visual race; the Python server owns scoring, deadlines, and inference. */
export default function WaldoGame() {
  const [duration, setDuration] = useState<number | string>(60);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [phase, setPhase] = useState<'idle' | 'loading' | 'countdown' | 'playing' | 'done'>('idle');
  const [countdown, setCountdown] = useState(3);
  const [match, setMatch] = useState<MatchState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rules, setRules] = useState(false);
  const [summary, setSummary] = useState(false);
  const [totals, setTotals] = useState<Totals>(readTotals);
  const socket = useRef<WebSocket | null>(null);
  const generation = useRef(0);
  const timer = useRef<number | null>(null);
  const recorded = useRef(false);
  const latest = useRef<MatchState | null>(null);
  const active = phase === 'playing';
  const locked = active || phase === 'loading' || phase === 'countdown';
  const seconds = Math.ceil((match?.remaining_ms ?? Number(duration) * 1000) / 1000);
  const validDuration = typeof duration === 'number' && Number.isInteger(duration) && duration >= 15 && duration <= 180;

  useEffect(() => {
    const controller = new AbortController();
    setCatalog(null); setError(null);
    void api<Catalog>('/api/waldo/catalog', { signal: controller.signal }).then(setCatalog).catch((failure: unknown) => {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : 'Bilder konnten nicht geladen werden.');
    });
    return () => controller.abort();
  }, []);

  useEffect(() => () => {
    generation.current += 1;
    if (timer.current !== null) window.clearTimeout(timer.current);
    socket.current?.close();
  }, []);

  function record(result: MatchState) {
    if (recorded.current || result.aborted || result.model_error || result.metrics.completed === 0) return;
    recorded.current = true;
    setTotals(old => {
      const next = { ...old, games: old.games + 1 };
      if (result.winner) next[result.winner] += 1;
      try { localStorage.setItem(storageKey, JSON.stringify(next)); } catch { /* Matches remain playable without storage. */ }
      return next;
    });
  }

  function connect(version: number) {
    if (generation.current !== version) return;
    const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/waldo/play?duration=${duration}`);
    socket.current = ws;
    ws.onmessage = event => {
      if (generation.current !== version) return;
      const message = JSON.parse(String(event.data)) as MatchState | { type: 'error'; message: string };
      if (message.type === 'error') { setError(message.message); setPhase('idle'); ws.close(); return; }
      latest.current = message; setMatch(message);
      if (message.ended) { setPhase('done'); setSummary(true); record(message); }
      else setPhase('playing');
    };
    ws.onerror = () => { if (generation.current === version) setError('Die Verbindung wurde unterbrochen. Bitte starte ein neues Duell.'); };
    ws.onclose = () => {
      if (generation.current !== version) return;
      if (!latest.current?.ended) {
        setPhase('idle');
        setError(previous => previous ?? 'Verbindung beendet. Dieses Duell wird nicht gewertet.');
      }
    };
  }

  async function startGame() {
    if (!catalog?.configured || !validDuration || locked) return;
    const version = ++generation.current;
    socket.current?.close(); setMatch(null); latest.current = null; recorded.current = false;
    setError(null); setSummary(false); setPhase('loading');
    try {
      await Promise.all(catalog.images.map(picture => new Promise<void>((resolve, reject) => {
        const image = new Image(); image.onload = () => resolve(); image.onerror = () => reject(new Error('Ein Spielbild fehlt. Bitte neu laden.')); image.src = picture.url;
      })));
      if (version !== generation.current) return;
      setCountdown(3); setPhase('countdown');
      const step = (value: number) => {
        timer.current = window.setTimeout(() => {
          if (version !== generation.current) return;
          if (value > 1) { setCountdown(value-1); step(value-1); }
          else connect(version);
        }, 1000);
      };
      step(3);
    } catch (failure) {
      if (version === generation.current) { setError(failure instanceof Error ? failure.message : 'Start fehlgeschlagen.'); setPhase('idle'); }
    }
  }

  function submit(point: Point, round: number) {
    if (active && socket.current?.readyState === WebSocket.OPEN) socket.current.send(JSON.stringify({ type: 'click', round, point }));
  }
  function skip() {
    if (active && socket.current?.readyState === WebSocket.OPEN) socket.current.send(JSON.stringify({ type: 'skip', round: match?.players.human.round }));
  }
  function stop() {
    if (socket.current?.readyState === WebSocket.OPEN) socket.current.send(JSON.stringify({ type: 'stop' }));
  }

  const metrics = match?.metrics;
  const progress = match ? match.remaining_ms / (match.duration * 1000) : 1;
  const resultTitle = match?.aborted ? 'Duell beendet.' : match?.winner === 'human' ? 'Dein Blick gewinnt.' : match?.winner === 'jev' ? 'Diese Runde geht an Jev.' : 'Gleichauf.';

  return <div className="er-page waldo-page">
    <BrandHeader game />
    <main className="waldo-main">
      <div className="waldo-intro"><div><p className="er-kicker"><span />Mensch vs. Jev</p><h1>Spot on<span>.</span></h1><p className="waldo-subtitle">Wer findet Waldo zuerst?</p></div>
        <div className="waldo-target"><img src="/api/waldo/images/target?v=3" alt="Gesucht: Waldo mit rot-weißem Shirt, Mütze und Brille" /><div><span>GESUCHT</span><strong>Waldo</strong><small>Klick ihn an.</small></div></div>
        <Tooltip label={`${totals.games} gewertete Duelle · ${totals.draw} Unentschieden · in diesem Browser gespeichert`}><div className="match-total"><Trophy size={15} /><span>Gesamtsiege</span><strong>Du {totals.human}<i>:</i>{totals.jev} Jev</strong></div></Tooltip>
      </div>

      <div className="waldo-controls">
        <div className="waldo-config"><div className="duration-field"><Clock3 size={16} /><NumberInput aria-label="Spielzeit in Sekunden" value={duration} onChange={setDuration} min={15} max={180} step={15} allowDecimal={false} allowNegative={false} disabled={locked} suffix=" s" size="sm" /></div>
          <button type="button" className="waldo-help" onClick={() => setRules(true)} aria-label="Spielregeln und Details"><CircleHelp size={18} /></button>
        </div>
        <div className={`waldo-clock ${active && seconds <= 10 ? 'urgent' : ''}`} role="timer" aria-label={`Restzeit ${seconds} Sekunden`}><span>{String(Math.floor(seconds / 60)).padStart(2, '0')}<b>:</b>{String(seconds % 60).padStart(2, '0')}</span></div>
        {active ? <button type="button" className="er-button secondary" onClick={stop}><Flag size={15} />Beenden</button>
          : <button type="button" className="er-button" disabled={locked || !catalog?.configured || !validDuration} onClick={() => void startGame()}>{phase === 'loading' ? <LoaderCircle className="spin" size={15} /> : phase === 'done' ? <RotateCcw size={15} /> : <Play size={15} fill="currentColor" />}{phase === 'loading' ? 'Bilder laden' : phase === 'countdown' ? 'Bereit machen' : phase === 'done' ? 'Revanche' : 'Duell starten'}</button>}
      </div>
      <div className="match-progress" aria-hidden="true"><span style={{ transform: `scaleX(${progress})` }} /></div>
      {error && <Alert color="red" title="Duell nicht verfügbar" className="waldo-alert">{error}</Alert>}
      {catalog && !catalog.configured && <Alert color="orange" className="waldo-alert">Bitte TYPESAFE_API_KEY auf dem Server hinterlegen.</Alert>}
      {match?.model_error && <Alert color="orange" className="waldo-alert" title="Jev pausiert">{match.model_error}<button type="button" className="inline-retry" onClick={() => socket.current?.send(JSON.stringify({ type: 'retry' }))}>Erneut versuchen</button></Alert>}

      <div className="waldo-arena">
        <Board who="human" player={match?.players.human} preview={catalog?.images[0]} active={active} started={!!match} modelError={false} onPick={submit} onSkip={skip} />
        <span className="arena-vs" aria-hidden="true">vs.</span>
        <Board who="jev" player={match?.players.jev} preview={catalog?.images[1]} active={active} started={!!match} modelError={!!match?.model_error} onPick={submit} onSkip={skip} />
        {phase === 'countdown' && <div className="waldo-countdown" role="status"><span key={countdown}>{countdown}</span><p>Gleiche Bilder. Gleiche Regeln.</p></div>}
      </div>

      <div className="waldo-underboard"><span><Check size={13} />Treffer +1 <i /> <X size={13} />Fehler −1</span><span>Gleiche Bildfolge · eigenes Tempo</span></div>
      <section className="waldo-telemetry" aria-label="Live-Messwerte von Jev">
        <div className="telemetry-speed"><span className="telemetry-icon"><Activity size={18} /></span><div><span className="telemetry-label">Letzte Antwort</span><strong>{metrics?.last_ms != null ? Math.round(metrics.last_ms) : '—'}<small>ms</small></strong></div><LatencyTrace values={metrics?.latencies ?? []} /></div>
        <div><Clock3 size={17} /><div><span className="telemetry-label">Ø Antwortzeit</span><strong>{metrics?.average_ms != null ? Math.round(metrics.average_ms) : '—'}<small>ms</small></strong></div></div>
        <div><Hash size={17} /><div><span className="telemetry-label">Jev-Aufrufe</span><strong>{metrics?.calls ?? 0}</strong></div></div>
        <Tooltip label={`${(metrics?.input_tokens ?? 0).toLocaleString('de-DE')} gemeldete Input-Tokens × $0.042 / Mio. · Output kostenlos. Offene und fehlgeschlagene Aufrufe können zusätzliche Kosten verursachen.`} multiline w={300}><div className="telemetry-cost"><Coins size={17} /><div><span className="telemetry-label">Kosten · geschätzt{metrics?.cost_partial ? '*' : ''}</span><strong>{dollars(metrics?.cost_usd ?? 0)}</strong></div></div></Tooltip>
      </section>
      <div className="waldo-measure-note">{phase === 'done' && <button onClick={() => setSummary(true)} type="button">Ergebnis ansehen <ArrowRight size={13} /></button>}<span>Jev 1.14 · Images + Box <span className="preview-label">Preview</span></span></div>
    </main>
    <footer className="er-footer"><span>Eraneos AI playground</span><a href="/waldo/referenzen">Referenzboxen prüfen & korrigieren ↗</a><button type="button" className="waldo-credit-button" onClick={() => setRules(true)}>Bilder & Details</button></footer>

    <Modal opened={rules} onClose={() => setRules(false)} title="Ein Duell. Ein klarer Maßstab." centered size="lg" className="waldo-modal">
      <div className="waldo-rules"><p><b>Klick auf Waldo.</b> Jev sucht ihn mit einer Box. Beide spielen dieselbe gemischte Bildfolge. Ein Treffer gibt <b>+1</b>, ein Fehler <b>−1</b>. Bei Fehlern bleibt das Bild; nach drei Fehlern geht es für beide automatisch weiter. „Weiter“ überspringt ein Bild für −1.</p>
        <p>Dein Klick zählt im sichtbaren Körperbereich mit 20 % Rand. Jevs Box erhält zum Kopf-Abgleich <b>30 % Rand pro Seite</b> und muss mindestens 50 % der Kopfbox umfassen. Mindestens 55 % seiner ursprünglichen Box müssen im Körperbereich mit 20 % Rand liegen. Kopf oder Körper zählen; ganze Szenen oder nur Füße nicht. Jevs Konfidenz beeinflusst die Wertung nicht. <a href="/waldo/referenzen">Referenzboxen prüfen ↗</a></p>
        <p>Nach jeder Antwort bleibt das Ergebnis 0,45 Sekunden sichtbar. Danach sucht Jev weiter. Angezeigte Antwortzeiten messen ausschließlich den API-Aufruf inklusive Netzwerk, ohne diese Anzeigepause. Nach Ablauf der Server-Uhr gibt es keine weiteren Punkte.</p>
        <p>Klare Suchbilder und schwierigere Szenen voller Menschen werden bei jedem Duell neu gemischt. In den Varianten steht Waldo an unterschiedlichen Positionen. Beide Spieler erhalten exakt dieselben Bilddateien; Jev bekommt keine Lösung oder Positionshinweise. Der Bildsatz wiederholt sich bei Bedarf.</p>
        <p><b>Tastatur:</b> Spielfeld fokussieren, Pfeiltasten bewegen den Zielpunkt. Enter bestätigt, Escape verwirft.</p>
        <details><summary>API & Kosten</summary><pre>{JSON.stringify({ model: 'jev-1.14.0', state: { scene: '<image reference>' }, questions: { waldo: { type: 'box', instructions: 'Where is Waldo in `scene`?' } } }, null, 2)}</pre><p>Header: TypeSafe-Danger-Zone-Images: true. Bild und Text werden als Input berechnet: $0.042 pro Million Tokens; Output kostenlos. Die Schätzung umfasst gemeldeten Verbrauch. Abgebrochene Aufrufe können trotzdem berechnet werden.</p><a href="https://docs.typesafe.ai/primitives/box" target="_blank" rel="noreferrer">TypeSafe Box-Dokumentation ↗</a></details>
        <p className="waldo-credit">Illustrationen: eigens mit Imagegen erstellt. Varianten: Waldo wird auf vorbereiteten Hintergründen platziert. Figur: Where’s Wally? / Where’s Waldo?, Martin Handford. Diese lokale Demo ist kein offizielles Spiel.</p>
      </div>
    </Modal>

    <Modal opened={summary} onClose={() => setSummary(false)} centered withCloseButton title="ZEIT FÜR DAS ERGEBNIS" size="md" className="waldo-modal result-modal">
      <div className="waldo-result"><span className="result-trophy"><Trophy size={30} strokeWidth={1.3} /></span><h2>{resultTitle}</h2><div className="result-score"><div><span>Du</span><strong>{match?.players.human.score ?? 0}</strong><Accuracy player={match?.players.human} /></div><i>:</i><div><span>Jev</span><strong>{match?.players.jev.score ?? 0}</strong><Accuracy player={match?.players.jev} /></div></div>
        <p>{match?.aborted ? 'Vorzeitig beendet · nicht in der Gesamtwertung.' : match?.model_error || !metrics?.completed ? 'Technische Unterbrechung · nicht in der Gesamtwertung.' : `${match?.players.human.hits ?? 0} zu ${match?.players.jev.hits ?? 0} Treffer · ${match?.duration ?? 60} Sekunden`}</p>
        <div className="result-metrics"><span>{metrics?.calls ?? 0} Aufrufe</span><span>{metrics?.average_ms != null ? `${Math.round(metrics.average_ms)} ms Ø` : '—'}</span><span>{dollars(metrics?.cost_usd ?? 0)}{metrics?.cost_partial ? '*' : ''}</span></div>
        <button className="er-button" type="button" onClick={() => void startGame()}><RotateCcw size={15} />Noch ein Duell</button><button className="result-dismiss" type="button" onClick={() => setSummary(false)}>Spielfeld ansehen</button>
      </div>
    </Modal>
  </div>;
}
