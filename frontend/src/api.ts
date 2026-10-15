/** Read a backend response, preserving useful server error messages. */
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new Error(apiError(body, response.status));
  if (body === null) throw new Error('The Python server returned an empty response.');
  return body as T;
}

/** Turn FastAPI error responses into safe, useful interface copy. */
export function apiError(body: unknown, status: number): string {
  const detail = typeof body === 'object' && body !== null && 'detail' in body ? body.detail : null;
  return typeof detail === 'string' ? detail : `Request failed (${status}). Check the Python server and try again.`;
}

/** Format a probability without implying measured accuracy. */
export function percent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

/** Make API identifiers readable without changing their values. */
export function humanize(value: string): string {
  return value.replaceAll('_', ' ').replaceAll('-', ' ');
}

/** Use seconds consistently when presenting observed request timings. */
export function seconds(milliseconds: number | null | undefined): string {
  return milliseconds == null ? '—' : `${(milliseconds / 1000).toFixed(2)} s`;
}

/** Preserve small token costs instead of rounding them down to zero cents. */
export function dollars(value: number | null | undefined): string {
  if (value == null) return '—';
  return value > 0 && value < 0.000001 ? '< $0.000001' : `$${value.toFixed(6)}`;
}
