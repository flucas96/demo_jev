import { useEffect, useRef, useState } from 'react';
import { Alert, Button, SegmentedControl, Slider } from '@mantine/core';
import { ArrowDown, ArrowUp, Braces, ChevronDown, Heart, Play, RotateCcw, Square, PersonStanding, Sparkles, Gauge, Timer, Infinity as InfinityIcon } from 'lucide-react';
import { dollars, percent } from '../api';
import { drawScene } from './scene';
import type { Action, Challenge, Frame, Mode, RenderState } from './types';
import './runner.css';

const actions = [
  { id: 'stand' as const, label: 'Upright', reward: '+1/m', key: '→', icon: PersonStanding },
  { id: 'jump' as const, label: 'Jump', reward: '0', key: '↑', icon: ArrowUp },
  { id: 'duck' as const, label: 'Duck', reward: '+0.2/m', key: '↓', icon: ArrowDown },
];

/** A real-time Jev demonstration with honest deadlines, inspectable choices, and seeded replay. */
export default function Runner() {
  const [mode, setMode] = useState<Mode>('jev');
  const [pace, setPace] = useState(1);
  const [challenge, setChallenge] = useState<Challenge>('endless');
  const pendingSince = useRef(0);
  const [frame, setFrame] = useState<Frame | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [inspect, setInspect] = useState(false);
  const [selectedTrace, setSelectedTrace] = useState<number | null>(null);
  const socket = useRef<WebSocket | null>(null);
  const canvas = useRef<HTMLCanvasElement | null>(null);
  const render = useRef<RenderState>({ frame: null, received: 0 });
  const active = connecting || frame?.phase === 'running';
  const last = frame?.history.at(-1);
  const decision = frame?.decision;
  const confidentChoice = decision?.status === 'ready' && decision.confidence != null
    ? actions.find(({ id }) => id === decision.action) : undefined;
  const shown = decision ?? last;
  const trace = selectedTrace === null ? shown : frame?.history.find((item) => item.id === selectedTrace);

  function changeSpeed(value: number) {
    setPace(value);
    if (socket.current?.readyState === WebSocket.OPEN) socket.current.send(JSON.stringify({ type: 'speed', pace: value }));
  }
  function stop(type: 'stop' | 'interrupt' = 'stop') {
    if (socket.current?.readyState === WebSocket.CONNECTING) { socket.current.close(); setConnecting(false); }
    if (socket.current?.readyState === WebSocket.OPEN) socket.current.send(JSON.stringify({ type }));
  }
  function choose(action: Action) {
    const current = render.current.frame;
    if (current?.mode === 'manual' && current.phase === 'running' && current.decision && socket.current?.readyState === WebSocket.OPEN) {
      socket.current.send(JSON.stringify({ type: 'action', action, encounter_id: current.decision.id }));
    }
  }
  function start(replay = false) {
    socket.current?.close();
    const seed = replay && frame ? frame.seed : crypto.getRandomValues(new Uint32Array(1))[0]! & 0x7fffffff;
    setError(null); setFrame(null); setSelectedTrace(null); setConnecting(true);
    render.current = { frame: null, received: performance.now() };
    const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/runner/play?mode=${mode}&seed=${seed}&pace=${pace}&challenge=${challenge}`);
    socket.current = ws;
    const timeout = window.setTimeout(() => { if (socket.current === ws && !render.current.frame) { setError('Connection timed out. Check the Python server.'); ws.close(); } }, 8000);
    ws.onmessage = (event: MessageEvent<string>) => {
      if (socket.current !== ws) return;
      try {
        const message = JSON.parse(event.data) as Frame | { type: 'error'; message: string };
        if (message.type === 'error') { setError(message.message); setConnecting(false); return; }
        if (message.type !== 'frame') return;
        clearTimeout(timeout); setConnecting(false);
        if (message.thinking && message.requests !== render.current.frame?.requests) pendingSince.current = performance.now();
        render.current = { frame: message, received: performance.now() }; setFrame(message);
        if (message.phase !== 'running') ws.close();
      } catch { setError('Invalid game update. Please restart the run.'); ws.close(); }
    };
    ws.onerror = () => { if (socket.current === ws) setError('Could not connect to the game server.'); };
    ws.onclose = () => {
      clearTimeout(timeout);
      if (socket.current !== ws) return;
      setConnecting(false);
      const current = render.current.frame;
      if (current?.phase === 'running') {
        const ended: Frame = { ...current, phase: 'interrupted', reason: 'Connection closed. Replay to start again.' };
        render.current.frame = ended; setFrame(ended);
      }
    };
  }

  useEffect(() => {
    const background = new Image(); background.src = '/runner/kyoto-dusk.png';
    const ctx = canvas.current?.getContext('2d');
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    let animation = 0;
    const paint = (now: number) => {
      if (ctx) drawScene(ctx, background, render.current, now, reducedMotion);
      animation = requestAnimationFrame(paint);
    };
    animation = requestAnimationFrame(paint);
    const keyboard = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement || (event.target instanceof Element && event.target.closest('[role="slider"]'))) return;
      const move = ({ ArrowUp: 'jump', ' ': 'jump', ArrowDown: 'duck', ArrowRight: 'stand' } as Record<string, Action>)[event.key];
      if (move && render.current.frame?.mode === 'manual' && render.current.frame.phase === 'running') { event.preventDefault(); choose(move); }
    };
    const visibility = () => { if (document.hidden) stop('interrupt'); };
    const watchdog = window.setInterval(() => {
      if (render.current.frame?.phase === 'running' && performance.now() - render.current.received > 2500) socket.current?.close();
    }, 500);
    document.addEventListener('keydown', keyboard); document.addEventListener('visibilitychange', visibility);
    return () => { cancelAnimationFrame(animation); clearInterval(watchdog); document.removeEventListener('keydown', keyboard); document.removeEventListener('visibilitychange', visibility); socket.current?.close(); socket.current = null; };
  }, []);

  const running = frame?.phase === 'running';
  const ended = frame && frame.phase !== 'running';
  const latency = shown?.latency_ms ?? last?.latency_ms;
  const endless = (active && frame ? frame.challenge : challenge) === 'endless';
  const livePace = active && frame ? frame.pace : pace;
  const waitingMs = Math.max(0, Math.round(performance.now() - pendingSince.current));
  return <section className="lantern-run" aria-label="Lantern Run game">
    <div className="runner-heading"><div><div className="runner-eyebrow"><span className="runner-seal" aria-hidden="true">京</span> KYOTO · DUSK</div><h1>Lantern Run<span>.</span></h1><p>Three moves. One model. Keep running.</p></div><div className="runner-controls"><SegmentedControl aria-label="Runner controller" value={mode} onChange={(value) => setMode(value as Mode)} disabled={!!active} data={[{ label: 'Jev plays', value: 'jev' }, { label: 'You play', value: 'manual' }]} /><div className="runner-speed"><Gauge size={14} /><span>{endless ? active ? 'Auto' : 'Start' : 'Speed'}</span><Slider thumbLabel="Game speed" min={0.5} max={2} step={0.25} value={pace} onChange={changeSpeed} disabled={connecting || (!!active && endless)} label={(value) => `${value}×`} color="#b57879" size="xs" thumbSize={13} /><output className="mono">{livePace.toFixed(2)}×</output></div></div></div>
    <div className="runner-mode-row"><SegmentedControl aria-label="Game mode" value={challenge} onChange={(value) => setChallenge(value as Challenge)} disabled={!!active} size="xs" data={[{label: <span><InfinityIcon size={14} />Endless</span>, value: 'endless'}, {label: <span><Timer size={13} />60 seconds</span>, value: 'timed'}]} /><span>{endless ? 'Faster until the last heart.' : 'Set your pace. Beat your score.'}</span></div>
    {error && <Alert color="red" className="runner-error">{error}</Alert>}
    <div className="runner-machine">
      <div className="runner-hud"><div className="runner-score"><span>SCORE</span><strong>{(frame?.score ?? 0) < 0 ? String(frame?.score) : String(frame?.score ?? 0).padStart(3, '0')}</strong></div><div className="runner-lives" aria-label={`${frame?.lives ?? 3} lives`}>{[0, 1, 2].map((life) => <Heart key={life} size={17} fill={life < (frame?.lives ?? 3) ? 'currentColor' : 'none'} className={life >= (frame?.lives ?? 3) ? 'lost' : ''} />)}</div><span className="runner-distance mono">{Math.floor(frame?.distance_m ?? 0)}<small> m</small></span><div className="runner-clock mono" title={endless ? 'Speed rises by 0.1× every 10 real seconds. No time limit.' : 'Game time — the clock follows the speed setting'}>{endless ? <><InfinityIcon size={17} /><strong>{(frame?.pace ?? pace).toFixed(2)}×</strong></> : <>{Math.max(0, Math.ceil((frame?.duration ?? 60) - (frame?.time ?? 0)))}<span> / 60s</span></>}</div></div>
      <div className="runner-stage"><canvas ref={canvas} width={640} height={360} aria-label="A courier runs through Kyoto, jumping crates and ducking hanging bamboo screens." />
        {running && frame.mode === 'jev' && confidentChoice && decision?.confidence != null && <div className="runner-thought-plane"><div className="runner-thought" data-action={confidentChoice.id} style={{ bottom: `${(74 + frame.player_y + frame.player_height) / 360 * 100}%` }} title="Jev’s reported confidence in this choice, not a measured chance of success." aria-label={`Jev chose ${confidentChoice.label} with ${percent(decision.confidence)} confidence`}><span className="runner-thought-action"><confidentChoice.icon size={13} />{confidentChoice.label}</span><span className="runner-thought-confidence"><strong>{Math.round(decision.confidence * 100)}<small>%</small></strong><span>confidence</span></span></div></div>}
        {!running && <div className="runner-overlay"><div className="runner-start-panel"><span className="runner-kicker">{ended ? frame.phase === 'finished' ? frame.lives === 0 ? 'GAME OVER' : 'RUN COMPLETE' : 'RUN ENDED' : 'A JEV ARCADE EXPERIMENT'}</span><h2>{ended ? `${frame.score} points` : 'Follow the lanterns.'}</h2><p>{ended ? frame.reason : mode === 'jev' ? 'Jev reads the course. You watch it decide.' : 'Your move happens immediately.'}</p><div className="runner-start-buttons"><Button color="#f2c58b" c="#292034" size="md" leftSection={connecting ? undefined : <Play size={15} fill="currentColor" />} loading={connecting} onClick={() => start()}>{ended ? 'New course' : mode === 'jev' ? 'Let Jev run' : 'Start running'}</Button>{ended && <Button variant="outline" color="#efd5b5" size="md" leftSection={<RotateCcw size={15} />} onClick={() => start(true)}>Replay seed</Button>}</div></div></div>}
        <div className="runner-call-count" title="Jev requests started in this run, including pending or failed requests. Resets with each new run or replay."><Sparkles size={13} />Jev calls <strong className="mono">{(frame?.requests ?? 0).toLocaleString('en-US')}</strong></div>
        {running && <div className="runner-live-tag"><span />{mode === 'jev' ? 'JEV LIVE' : 'MANUAL'}</div>}
      </div>
      <div className="runner-console"><div className="runner-decision-label"><Sparkles size={15} /><span>{!running ? 'The next move' : mode === 'jev' ? frame?.thinking ? 'Jev deciding continuously' : decision?.status === 'error' ? 'Retrying request' : 'Applying decision' : decision ? 'Your move' : 'Approaching next obstacle'}</span><small className="runner-latency mono" title="Real response time from the Python server, including the TypeSafe network round trip. Game speed does not scale this measurement."><Timer size={12} />{mode === 'manual' ? 'Instant controls' : latency != null ? `${Math.round(latency)} ms` : running && frame?.thinking ? `${waitingMs} ms waiting` : 'Live response time'}</small></div><div className="runner-actions">{actions.map(({ id, label, reward, key, icon: Icon }) => <button key={id} type="button" className={`runner-action ${frame?.action === id ? 'chosen' : ''}`} disabled={!running || mode !== 'manual' || !decision || decision.seconds_left <= 0} onClick={() => choose(id)} aria-label={`Choose ${label}`} aria-pressed={frame?.action === id}><Icon size={22} /><span>{label}<small>{mode === 'manual' ? key : decision?.probabilities[id] == null ? reward : percent(decision.probabilities[id])}</small></span>{frame?.action === id && <span className="runner-action-dot" />}</button>)}</div></div>
    </div>
    <div className="runner-bottom"><div className="runner-rewards"><span><PersonStanding size={14} />+1/m</span><span><ArrowDown size={14} />+0.2/m</span><span><ArrowUp size={14} />0</span><span className="runner-penalty"><Heart size={13} />−25</span></div><div className="runner-cost" title="Estimate from reported input tokens. Aborted requests may incur unreported cost. Unknown model pricing is shown as a dash.">Est. cost <strong className="mono">{dollars(frame?.estimated_cost_usd)}</strong></div>{active && <button className="runner-stop" onClick={() => stop()} type="button"><Square size={12} />Stop</button>}</div>
    {ended && <div className="runner-results"><div><strong>{frame.correct}<small> / {frame.presented}</small></strong><span>Optimal decisions</span></div><div><strong>{frame.timely}<small> / {frame.presented}</small></strong><span>Answered encounters</span></div><div><strong>{frame.collisions}</strong><span>Collisions</span></div><div><strong>{frame.misses + frame.errors}</strong><span>Misses / errors</span></div></div>}
    <button className="runner-inspect-toggle" type="button" onClick={() => setInspect(!inspect)} aria-expanded={inspect}><Braces size={16} />Under the hood<span>{frame ? `Seed ${frame.seed}` : 'Text in → choice out'}</span><ChevronDown size={15} style={{ transform: inspect ? 'rotate(180deg)' : undefined }} /></button>
    {inspect && <div className="runner-inspector"><p>Moves begin on receipt of Jev’s response. The speed slider changes game time, not measured API latency. Jev is queried continuously: each answer immediately starts the next request with fresh state, including empty road. Only one request is in flight. Repeating jump continues the same jump. Obstacle urgency accounts for measured API response time. Stale responses are discarded; late moves can collide. Points come only from distance: upright 1/m, ducking 0.2/m, jumping 0. Collisions cost 25 points. Timed mode lasts 60 game seconds. Endless adds 0.1× speed every 10 real seconds and continues until all hearts are lost. Scoring does not train the model.</p><div className="runner-inspect-meta"><span>{frame?.mode === 'manual' ? 'Manual · no API calls' : frame?.model ?? 'Choice · jev-latest'}</span><span>{frame?.responses ?? 0} responses / {frame?.requests ?? 0} requests</span><span>{frame?.input_tokens ?? 0} input tokens</span><span>{frame?.output_tokens ?? 0} output tokens</span><span>{shown?.latency_ms == null ? 'No response yet' : `${shown.latency_ms.toFixed(0)} ms last response`}</span></div>{!!frame?.history.length && <div className="runner-history-wrap"><p className="runner-history-note">Latest 50 encounters · totals cover the entire run</p><table><thead><tr><th>Gate</th><th>Obstacle</th><th>Chosen</th><th>Optimal</th><th>Outcome</th><th>Penalty</th></tr></thead><tbody>{frame.history.map((item) => <tr key={item.id} className={selectedTrace === item.id ? 'selected' : ''}><td><button onClick={() => setSelectedTrace(item.id)}>#{item.id}</button></td><td>{item.kind}</td><td>{item.action ?? item.status}</td><td>{item.expected}</td><td>{item.collision ? item.collision_reason ?? 'Collision' : item.optimal ? 'Optimal' : 'Safe'}</td><td>{item.reward > 0 ? '+' : ''}{item.reward}</td></tr>)}</tbody></table></div>}<div className="runner-code-grid"><div><h3>Request {selectedTrace !== null && <button onClick={() => setSelectedTrace(null)}>Show latest</button>}</h3><pre>{trace?.request ?? 'Start a run to inspect the exact text sent to Jev.'}</pre></div><div><h3>Response</h3><pre>{trace?.response ?? trace?.error ?? 'Waiting for a decision.'}</pre></div></div></div>}
  </section>;
}
