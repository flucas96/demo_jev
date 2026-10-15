import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api';
import type { Catalog, Comparison, MatchState, ModelCatalog, Point, Run } from './types';

export const JEV = 'jev-1.14.0';
const recoveryKey = 'waldo-comparison-v3';

/** Recovery is per tab; the authoritative history stays on the server. */
function remember(id: string | null) {
  try { if (id) sessionStorage.setItem(recoveryKey, id); else sessionStorage.removeItem(recoveryKey); } catch { /* Optional browser storage. */ }
}

/** Share one live game lifecycle between the playground and guided presentation. */
export default function useWaldoGame(pairedMode = true) {
  const [duration, setDuration] = useState<number | string>(60);
  const [model, setModel] = useState('claude-opus-5-5');
  const [models, setModels] = useState<ModelCatalog | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [phase, setPhase] = useState<'idle' | 'loading' | 'countdown' | 'playing' | 'done'>('idle');
  const [countdown, setCountdown] = useState(3);
  const [match, setMatch] = useState<MatchState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const socket = useRef<WebSocket | null>(null);
  const generation = useRef(0);
  const timer = useRef<number | null>(null);
  const latest = useRef<MatchState | null>(null);
  const launching = useRef(false);
  const active = phase === 'playing';
  const locked = active || phase === 'loading' || phase === 'countdown';
  const paired = pairedMode && model !== JEV;
  const pendingPair = !!comparison && comparison.next_stage < 3;
  const nextStage = comparison?.next_stage === 2 ? 2 : 1;
  const selected = models?.models.find(option => option.id === model);
  const upcomingLabel = nextStage === 2 ? 'Jev' : selected?.label.replace(' · Solo', '') ?? 'LLM';
  const currentLabel = match?.model_label ?? upcomingLabel;
  const currentModel = match?.metrics.model ?? (nextStage === 2 ? JEV : model);
  const validDuration = typeof duration === 'number' && Number.isInteger(duration) && duration >= 15 && duration <= 180;
  const canStart = !!catalog && validDuration && !!models && (!pairedMode || model !== JEV) &&
    (!(pairedMode || model === JEV) || models.jev_configured) &&
    (nextStage === 2 || (!!selected && (model === JEV || models.gateway_configured)));

  useEffect(() => {
    const controller = new AbortController();
    const init = { signal: controller.signal };
    void Promise.all([api<Catalog>('/api/waldo/catalog', init), api<ModelCatalog>('/api/waldo/models', init), api<Run[]>('/api/waldo/leaderboard', init)])
      .then(async ([images, choices, history]) => {
        if (controller.signal.aborted) return;
        setCatalog(images); setModels(choices); setRuns(history);
        if (!choices.models.some(option => option.id === choices.default_model) && choices.models[0]) setModel(choices.models[0].id);
        let saved: string | null = null;
        try { saved = pairedMode ? sessionStorage.getItem(recoveryKey) : null; } catch { /* Recovery is optional. */ }
        if (saved) {
          const restored = await api<Comparison>(`/api/waldo/comparisons/${encodeURIComponent(saved)}`, init).catch(() => null);
          if (controller.signal.aborted) return;
          if (restored && restored.next_stage < 3) { setComparison(restored); setModel(restored.model); setDuration(restored.duration); }
          else remember(null);
        }
      }).catch((failure: unknown) => { if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : 'Could not load the game.'); });
    return () => controller.abort();
  }, [pairedMode]);

  useEffect(() => () => {
    generation.current += 1;
    if (timer.current !== null) window.clearTimeout(timer.current);
    socket.current?.close();
  }, []);

  function refreshHistory() {
    void api<Run[]>('/api/waldo/leaderboard').then(history => { setRuns(history); setHistoryError(null); })
      .catch(() => setHistoryError('Could not load the leaderboard. Please reload.'));
  }

  const startGame = useCallback(async () => {
    if (!canStart || locked || !catalog || launching.current) return;
    launching.current = true;
    const version = ++generation.current;
    socket.current?.close(); setMatch(null); latest.current = null;
    setError(null); setPhase('loading');
    try {
      let pair = paired && comparison?.next_stage !== 3 ? comparison : null;
      if (paired && !pair) {
        pair = await api<Comparison>('/api/waldo/comparisons', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model, duration }) });
        if (version !== generation.current) return;
        setComparison(pair); remember(pair.id);
      }
      const round = pair?.next_stage === 2 ? 2 : 1;
      await Promise.all(catalog.images.map(picture => new Promise<void>((resolve, reject) => {
        const image = new Image(); image.onload = () => resolve(); image.onerror = () => reject(new Error('An image could not load. Please reload.')); image.src = picture.url;
      })));
      if (version !== generation.current) return;
      setCountdown(3); setPhase('countdown');
      const connect = () => {
        if (generation.current !== version) return;
        const query = pair ? `comparison_id=${encodeURIComponent(pair.id)}&stage=${round}` : `duration=${duration}&model=${encodeURIComponent(model)}`;
        const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/waldo/play?${query}`);
        socket.current = ws;
        ws.onmessage = event => {
          if (generation.current !== version) return;
          const message = JSON.parse(String(event.data)) as MatchState | { type: 'error'; message: string };
          if (message.type === 'error') { setError(message.message); setPhase('idle'); ws.close(); return; }
          latest.current = message; setMatch(message);
          if (!message.ended) { setPhase('playing'); return; }
          setPhase('done'); refreshHistory();
          if (pair && message.status === 'completed') {
            setComparison({ ...pair, next_stage: round === 1 ? 2 : 3 });
            if (round === 2) remember(null);
          }
        };
        ws.onerror = () => { if (generation.current === version) setError('Connection interrupted.'); };
        ws.onclose = () => {
          if (generation.current !== version) return;
          if (!latest.current?.ended) { setPhase('idle'); setError(previous => previous ?? 'Connection closed. This run is saved as incomplete.'); refreshHistory(); }
        };
      };
      const step = (value: number) => {
        timer.current = window.setTimeout(() => {
          if (version !== generation.current) return;
          if (value > 1) { setCountdown(value - 1); step(value - 1); }
          else connect();
        }, 1000);
      };
      step(3);
    } catch (failure) {
      if (version === generation.current) { setError(failure instanceof Error ? failure.message : 'Could not start the game.'); setPhase('idle'); }
    } finally { launching.current = false; }
  }, [canStart, locked, catalog, paired, comparison, model, duration]);

  function reset() {
    generation.current += 1;
    socket.current?.close();
    if (timer.current !== null) window.clearTimeout(timer.current);
    setComparison(null); remember(null); setMatch(null); latest.current = null; setPhase('idle'); setError(null);
  }
  function selectModel(value: string) { reset(); setModel(value); }
  function send(message: object) { if (socket.current?.readyState === WebSocket.OPEN) socket.current.send(JSON.stringify(message)); }
  function submit(point: Point, round: number) { if (active) send({ type: 'click', round, point }); }
  function skip() { if (active) send({ type: 'skip', round: match?.players.human.round }); }
  function stop() { send({ type: 'stop' }); }
  function retry() { send({ type: 'retry' }); }

  return { pairedMode, duration, setDuration, model, selectModel, models, catalog, comparison, runs, phase, countdown,
    match, error, historyError, active, locked, paired, pendingPair, nextStage, selected,
    upcomingLabel, currentLabel, currentModel, canStart, startGame, reset, submit, skip, stop, retry };
}

export type WaldoGameState = ReturnType<typeof useWaldoGame>;
