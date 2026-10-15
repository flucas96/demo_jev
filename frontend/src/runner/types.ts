export type Action = 'stand' | 'jump' | 'duck';
export type Mode = 'jev' | 'manual';
export type Challenge = 'timed' | 'endless';
export type DecisionStatus = 'upcoming' | 'pending' | 'ready' | 'missed' | 'error';
export interface Decision {
  id: number; status: DecisionStatus; action: Action | null; seconds_left: number;
  probabilities: Partial<Record<Action, number>>; confidence: number | null;
  latency_ms: number | null; request: string | null; response: string | null; error: string | null;
}
export interface Trace {
  id: number; kind: string; action: Action | null; expected: Action; status: DecisionStatus;
  collision: boolean; collision_reason: string | null; optimal: boolean; reward: number; latency_ms: number | null;
  request: string | null; response: string | null; error: string | null;
}
export interface Obstacle {
  id: number; kind: string; x: number; width: number; bottom: number; top: number;
  trigger_in: number; resolved: boolean;
}
export interface Frame {
  type: 'frame'; run_id: string; seed: number; mode: Mode; time: number; duration: number | null; challenge: Challenge; collisions: number;
  phase: 'running' | 'finished' | 'interrupted'; reason: string | null;
  score: number; lives: number; action: Action; action_age: number; player_y: number;
  player_height: number; speed: number; pace: number; distance_m: number; jump_duration: number; hit: boolean; obstacles: Obstacle[];
  decision: Decision | null; history: Trace[]; presented: number; timely: number;
  correct: number; misses: number; errors: number; input_tokens: number; output_tokens: number;
  estimated_cost_usd: number | null; model: string | null;
  thinking: boolean; requests: number; responses: number;
}
export interface RenderState { frame: Frame | null; received: number }
