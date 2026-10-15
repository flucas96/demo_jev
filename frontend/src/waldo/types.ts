export interface Box { left: number; right: number; top: number; bottom: number }
export interface Point { x: number; y: number }
export interface Puzzle { id: string; url: string; width: number; height: number; title: string }
export interface Catalog { configured: boolean; model: string; images: Puzzle[] }
export interface ReferencePuzzle extends Puzzle { reference: Box; head: Box; tolerance: Box }
export interface ReferenceCatalog { head_coverage: number; box_precision: number; padding: number; answer_padding: number; images: ReferencePuzzle[] }
export interface Feedback {
  correct: boolean; skipped: boolean; iou: number; box: Box | null; scoring_box: Box | null;
  point: Point | null;
  confidence: number | null; elapsed_ms: number | null; advance: boolean;
}
export interface Player {
  round: number; score: number; hits: number; misses: number; puzzle: Puzzle; feedback: Feedback | null;
}
export interface Metrics {
  calls: number; completed: number; failures: number; input_tokens: number; output_tokens: number;
  cost_usd: number; cost_partial: boolean; last_ms: number | null; average_ms: number | null;
  latencies: number[]; model: string;
}
export interface MatchState {
  type: 'state'; remaining_ms: number; duration: number; ended: boolean; aborted: boolean;
  winner: 'human' | 'jev' | 'draw' | null; model_error: string | null;
  players: { human: Player; jev: Player }; metrics: Metrics;
}
export interface Totals { human: number; jev: number; draw: number; games: number }
