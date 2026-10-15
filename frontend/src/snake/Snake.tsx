import { useEffect, useRef, useState } from 'react';
import { Alert, Button } from '@mantine/core';
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Braces, Cherry, Play, RotateCcw, Sparkles, Square, Timer } from 'lucide-react';
import { dollars, percent } from '../api';
import './snake.css';

type Direction = 'up' | 'right' | 'down' | 'left';
type Cell = [number, number];
interface Choice { choice: Direction; confidence: number; probabilities: Record<Direction, number> }
interface Frame {
  type: 'frame'; phase: 'running' | 'lost' | 'won' | 'stopped'; reason: string | null;
  seed: number; size: number; snake: Cell[]; food: Cell | null; direction: Direction;
  score: number; steps: number; board: string; sent_board: string | null;
  sent_step: number | null; decision_step: number | null; requests: number; responses: number;
  thinking: boolean; decision: Choice | null; latency_ms: number | null; input_tokens: number;
  estimated_cost_usd: number | null; request: unknown; response_request: unknown; response: unknown;
}
const arrows = { up: ArrowUp, right: ArrowRight, down: ArrowDown, left: ArrowLeft };
const directions: Direction[] = ['up', 'right', 'down', 'left'];
const previewSnake: Cell[] = [[4, 5], [3, 5], [2, 5]];
const sameCell = (a: Cell | null, x: number, y: number) => a?.[0] === x && a[1] === y;

/** Display the authoritative Python board alongside the exact ASCII observation sent to Jev. */
export default function Snake() {
  const [frame, setFrame] = useState<Frame | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const socket = useRef<WebSocket | null>(null);
  const current = useRef<Frame | null>(null);
  const active = connecting || frame?.phase === 'running';
  const size = frame?.size ?? 10;
  const snake = frame?.snake ?? previewSnake;
  const food: Cell | null = frame ? frame.food : [7, 3];
  const Heading = arrows[frame?.direction ?? 'right'];
  const observationParts = frame?.sent_board?.split('\n\n') ?? [];

  function stop() {
    if (socket.current?.readyState === WebSocket.OPEN) socket.current.send(JSON.stringify({ type: 'stop' }));
    else socket.current?.close();
  }
  function start(replay = false) {
    socket.current?.close();
    const seed = replay && frame ? frame.seed : crypto.getRandomValues(new Uint32Array(1))[0]! & 0x7fffffff;
    setError(null); setFrame(null); setConnecting(true); current.current = null;
    const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/snake/play?seed=${seed}`);
    socket.current = ws;
    const timeout = window.setTimeout(() => {
      if (socket.current === ws && !current.current) { setError('Connection timed out. Check the Python server.'); ws.close(); }
    }, 8000);
    ws.onmessage = (event: MessageEvent<string>) => {
      if (socket.current !== ws) return;
      try {
        const message = JSON.parse(event.data) as Frame | { type: 'error'; message: string };
        if (message.type === 'error') { setError(message.message); ws.close(); return; }
        if (message.type !== 'frame') return;
        clearTimeout(timeout); setConnecting(false); current.current = message; setFrame(message);
        if (message.phase !== 'running') ws.close();
      } catch { setError('Invalid game update. Start a new game.'); ws.close(); }
    };
    ws.onerror = () => { if (socket.current === ws) setError('Could not connect to the Snake server.'); };
    ws.onclose = () => {
      clearTimeout(timeout);
      if (socket.current !== ws) return;
      setConnecting(false);
      if (current.current?.phase === 'running') {
        const ended: Frame = { ...current.current, phase: 'stopped', reason: 'Connection closed.', thinking: false };
        current.current = ended; setFrame(ended);
      }
    };
  }
  useEffect(() => {
    const visibility = () => { if (document.hidden) stop(); };
    document.addEventListener('visibilitychange', visibility);
    return () => { document.removeEventListener('visibilitychange', visibility); socket.current?.close(); socket.current = null; };
  }, []);

  return <section className="snake-demo" aria-label="Jev Snake game">
    <header className="snake-heading"><div><span className="snake-eyebrow">THE CHARACTER ARCADE</span><h1>Snake<span>.</span></h1><p>A board of characters. A model at the controls.</p></div><div className="snake-cadence"><Sparkles size={17} /><span>One answer<strong>One move</strong></span></div></header>
    {error && <Alert color="red" mb="md">{error}</Alert>}
    <div className="snake-layout">
      <div className="snake-machine">
        <div className="snake-hud"><span><Cherry size={17} /><strong>{String(frame?.score ?? 0).padStart(2, '0')}</strong><small>FOOD</small></span><span className="snake-calls" title="Requests started this run, including pending requests."><Sparkles size={14} />Jev calls <strong>{frame?.requests ?? 0}</strong></span><span><Timer size={14} /><strong>{frame?.latency_ms == null ? '—' : `${Math.round(frame.latency_ms)} ms`}</strong></span></div>
        <div className="snake-board-shell">
          <div className={`snake-board ${frame?.phase === 'lost' ? 'snake-lost' : ''}`} role="img" aria-label={`Snake board: ${snake.length} cells long, ${frame?.score ?? 0} food collected, moving ${frame?.direction ?? 'right'}.`} style={{ gridTemplateColumns: `repeat(${size}, 1fr)` }}>
            {Array.from({ length: size * size }, (_, i) => {
              const x = i % size, y = Math.floor(i / size);
              const index = snake.findIndex((cell) => sameCell(cell, x, y));
              return <div key={i} className={`snake-cell ${index === 0 ? 'head' : index > 0 ? 'body' : ''} ${index === snake.length - 1 ? 'tail' : ''} ${sameCell(food, x, y) ? 'food' : ''}`}>{index === 0 ? <Heading size={22} /> : sameCell(food, x, y) ? <Cherry size={21} /> : null}</div>;
            })}
          </div>
          {!active && <div className="snake-game-overlay"><span>{frame ? frame.phase === 'won' ? 'BOARD COMPLETE' : frame.phase === 'lost' ? 'GAME OVER' : 'RUN ENDED' : 'READY WHEN YOU ARE'}</span><h2>{frame ? `${frame.score} food collected` : 'Let the model play.'}</h2><p>{frame?.reason ?? 'No pixels sent. Just characters.'}</p><div><Button color="#c6dc96" c="#203425" leftSection={<Play size={14} />} onClick={() => start()}>{frame ? 'New game' : 'Let Jev play'}</Button>{frame && <Button color="#e3e8d4" variant="subtle" leftSection={<RotateCcw size={14} />} onClick={() => start(true)}>Replay seed</Button>}</div></div>}
          {connecting && <div className="snake-connecting">Connecting…</div>}
        </div>
        <div className="snake-machine-footer"><span><span className={`snake-status-dot ${active ? 'active' : ''}`} />{active ? frame?.thinking ? 'Jev is thinking' : 'Applying answer' : 'One answer · one move'}</span><span className="mono">{frame?.steps ?? 0} moves · {snake.length} length</span>{active && <button type="button" onClick={stop}><Square size={12} />Stop</button>}</div>
      </div>
      <aside className="snake-observation">
        <div className="snake-panel-heading"><Braces size={18} /><h2>What Jev sees</h2><span>{frame?.sent_step == null ? 'TEXT ONLY' : `MOVE ${frame.sent_step}`}</span></div>
        <div className="snake-ascii-wrap">{frame?.sent_board ? <div className="snake-exact-observation" aria-label="Exact board and cell descriptions sent to Jev">{observationParts.map((part, index) => <pre key={index} className={index === observationParts.length - 1 ? 'snake-coordinate-board' : 'snake-state-context'}>{part}</pre>)}</div> : <div className="snake-ascii-empty"><Braces size={28} /><p>The board and neighboring cells<br />appear here when you start.</p></div>}</div>
        <div className="snake-legend"><span><b>H</b>Head</span><span><b>o</b>Body</span><span><b>T</b>Tail</span><span><b>*</b>Food</span><span><b>#</b>Wall</span><span><b>.</b>Empty</span></div>
        <div className="snake-choice-heading"><span>LAST RESPONSE</span><strong>{frame?.decision ? `${percent(frame.decision.confidence)} confidence` : '—'}</strong></div>
        <div className="snake-choices">{directions.map((direction) => { const Icon = arrows[direction]; return <div key={direction} className={frame?.decision?.choice === direction ? 'selected' : ''} title={direction}><Icon size={20} /><span>{frame?.decision ? `${Math.round(frame.decision.probabilities[direction] * 100)}%` : '—'}</span></div>; })}</div>
        <p className="snake-timing-note">{frame?.decision_step != null ? `Answer for move ${frame.decision_step}. ` : ''}The board waits for Jev’s next answer.</p>
      </aside>
    </div>
    <div className="snake-bottom"><span>One request at a time. Latest board in, direction out.</span><span title="Estimate from reported input tokens. Cancelled requests may incur unreported cost.">Est. cost <strong className="mono">{dollars(frame?.estimated_cost_usd)}</strong></span></div>
    <details className="snake-inspector"><summary><Braces size={15} />Under the hood<span>{frame ? `Seed ${frame.seed}` : 'ASCII → Choice → Move'}</span></summary><p>Python owns the board. Every validated Jev answer moves the snake exactly one cell. Jev receives the full character board, its current heading, and factual contents of the four neighboring cells. Python reads those cells but provides no safe-move labels, ranking, or pathfinding. The exact input is shown above; fixed game rules describe all four actions. The snake stays still while Jev thinks, so every answer acts on the exact board it received. Reversing into the body ends the game. One request runs at a time, and only changed boards are sent. API errors stop the run. Hiding the tab stops play.</p><div><pre>{frame?.request ? JSON.stringify(frame.response_request ?? frame.request, null, 2) : 'Start a game to see the exact request.'}</pre><pre>{frame?.response ? JSON.stringify(frame.response, null, 2) : 'Waiting for a response.'}</pre></div></details>
  </section>;
}
