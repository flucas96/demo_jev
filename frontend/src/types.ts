export interface ChoiceQuestion {
  type: 'choice';
  instructions: string;
  criteria: Record<string, string>;
}

export interface ScoreQuestion {
  type: 'score';
  instructions: string;
  criteria: string[];
}

export interface NoulQuestion {
  type: 'noul';
  instructions: string;
  criteria?: Record<string, string>;
}

export interface Questions {
  choice: ChoiceQuestion;
  score: ScoreQuestion;
  noul: NoulQuestion;
}

export interface Scenario {
  id: string;
  title: string;
  eyebrow: string;
  description: string;
  icon: string;
  choice_label: string;
  score_label: string;
  noul_label: string;
  score_labels: string[];
  examples: { id: string; title: string; text: string; tag: string }[];
  questions: Questions;
  policy_description: string;
  docs_url: string;
}

export interface ChoiceAnswer {
  type: 'choice';
  choice: string;
  confidence: number;
  probabilities: Record<string, number>;
}

export interface ScoreAnswer {
  type: 'score';
  score: number;
  confidence: number;
  probabilities: Record<string, number>;
  legend: Record<string, string>;
}

export interface TypeSafeResponse {
  model: string;
  answers: {
    choice: ChoiceAnswer;
    score: ScoreAnswer;
    noul: { type: 'noul'; noul: number };
  };
  usage: { input_tokens: number; output_tokens: number };
}

export interface Decision {
  action: 'route' | 'review' | 'escalate';
  destination: string;
  label: string;
  reasons: string[];
  threshold: number;
}

export interface Evaluation {
  source: 'live';
  request: { model: string; state: string; questions: Questions };
  response: TypeSafeResponse;
  elapsed_ms: number;
  estimated_cost_usd: number | null;
  decision: Decision;
}

export interface Health {
  configured: boolean;
  model: string;
}

export interface Ticket {
  id: string;
  title: string;
  text: string;
  tag: string;
}

export interface BatchSummary {
  total: number;
  succeeded: number;
  failed: number;
  elapsed_ms: number;
  tickets_per_second: number;
  p50_ms: number | null;
  p95_ms: number | null;
  max_in_flight: number;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: number | null;
  model: string | null;
  concurrency: number;
}

export type BatchEvent =
  | { type: 'started'; total: number; concurrency: number }
  | { type: 'ticket_started'; ticket_id: string; started_ms: number; active: number }
  | { type: 'ticket_completed'; ticket_id: string; started_ms: number; finished_ms: number; evaluation: Evaluation }
  | { type: 'ticket_failed'; ticket_id: string; started_ms: number; finished_ms: number; error: string }
  | { type: 'finished'; summary: BatchSummary };
