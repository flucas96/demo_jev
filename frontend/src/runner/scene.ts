import type { Action, RenderState } from './types';

const GROUND = 286;

/** Draw a tiny courier using explicit pixel shapes, keeping the collision body readable. */
function courier(ctx: CanvasRenderingContext2D, x: number, feet: number, action: Action, time: number, hit: boolean) {
  const duck = action === 'duck';
  const step = Math.floor(time * 11) % 2;
  const top = feet - (duck ? 19 : 40);
  const box = (color: string, dx: number, dy: number, w: number, h: number) => {
    ctx.fillStyle = color; ctx.fillRect(Math.round(x + dx), Math.round(top + dy), w, h);
  };
  ctx.globalAlpha = hit && step ? 0.45 : 1;
  if (duck) {
    box('#151928', -12, 3, 24, 16); box('#e9b992', 4, 3, 8, 8);
    box('#181c31', 2, 0, 12, 4); box('#6978a2', -10, 7, 14, 8);
    box('#c85762', -14, 3, 18, 4); box('#e5d0ad', -10, 16, 20, 3);
  } else {
    box('#151928', -9, 0, 18, 13); box('#edbd96', -5, 5, 13, 9);
    box('#232b44', -9, 0, 18, 5); box('#232b44', -9, 4, 4, 8);
    box('#101726', 5, 7, 2, 2); box('#8796bb', -8, 14, 16, 15);
    box('#4d5e89', -8, 17, 8, 14); box('#c85762', -9, 13, 18, 4);
    box('#c85762', -20, 12 + step * 2, 13, 4); box('#ec8590', -24, 14 + step * 2, 6, 3);
    box('#e9b992', 8, 21, 4, 7); box('#1e2947', -8, 29, 16, 5);
    box('#253150', -8 + step * 3, 33, 6, 5); box('#253150', 3 - step * 3, 33, 6, 5);
    box('#f0d7b7', -10 + step * 3, 38, 8, 2); box('#f0d7b7', 3 - step * 3, 38, 8, 2);
  }
  ctx.globalAlpha = 1;
}

/** Interpolate rendering between server snapshots; all collisions and points remain in Python. */
export function drawScene(ctx: CanvasRenderingContext2D, background: HTMLImageElement, state: RenderState, now: number, reducedMotion: boolean) {
  const frame = state.frame;
  const active = frame?.phase === 'running';
  const interpolation = active ? Math.min(0.1, Math.max(0, (now - state.received) / 1000)) : 0;
  const time = frame ? frame.time + interpolation * frame.pace : reducedMotion ? 0 : now / 1000;
  ctx.imageSmoothingEnabled = false;
  ctx.fillStyle = '#24213e'; ctx.fillRect(0, 0, 640, 360);
  if (background.complete && background.naturalWidth) {
    ctx.drawImage(background, -Math.min(18, (frame?.time ?? 0) * 0.3), -8, 666, 375);
  }
  ctx.fillStyle = '#181d30'; ctx.fillRect(0, GROUND + 8, 640, 74);
  ctx.fillStyle = '#9a7580'; ctx.fillRect(0, GROUND, 640, 3);
  ctx.fillStyle = '#5c4b65'; ctx.fillRect(0, GROUND + 3, 640, 5);
  const scroll = frame ? frame.distance_m * 10 + interpolation * frame.speed : 0;
  for (let row = 0; row < 4; row++) {
    for (let col = -1; col < 19; col++) {
      const x = Math.round(col * 40 - scroll % 40 + (row % 2) * 20);
      ctx.fillStyle = row % 2 ? '#27273d' : '#2d2a40';
      ctx.fillRect(x, GROUND + 12 + row * 16, 37, 13);
      ctx.fillStyle = '#363048'; ctx.fillRect(x + 2, GROUND + 12 + row * 16, 30, 1);
    }
  }
  if (!reducedMotion) for (let n = 0; n < 11; n++) {
    const x = (n * 71 + 660 - time * (6 + n % 3)) % 660;
    const y = 55 + (n * 23 + time * (4 + n % 4)) % 210;
    ctx.fillStyle = n % 2 ? '#e4a0aa88' : '#bf788988';
    ctx.fillRect(Math.round(x), Math.round(y), 3, 2);
  }
  for (const obstacle of frame?.obstacles ?? []) {
    const x = Math.round(obstacle.x - interpolation * frame!.speed);
    const w = Math.round(obstacle.width);
    if (obstacle.kind === 'crate') {
      const y = GROUND - Math.round(obstacle.top);
      ctx.fillStyle = '#302335'; ctx.fillRect(x - 2, y - 2, w + 4, obstacle.top + 2);
      ctx.fillStyle = '#b67b51'; ctx.fillRect(x, y, w, obstacle.top);
      ctx.fillStyle = '#e3af6f'; ctx.fillRect(x, y, w, 3);
      ctx.fillStyle = '#654636'; ctx.fillRect(x + 3, y + 4, w - 6, obstacle.top - 7);
      ctx.fillStyle = '#c18a57';
      for (let i = 0; i < w - 4; i += 3) ctx.fillRect(x + 2 + i, y + 3 + i * (obstacle.top - 8) / w, 4, 4);
      ctx.fillRect(x + 2, y + obstacle.top - 4, w - 4, 3);
    } else if (obstacle.kind === 'beam') {
      const y = GROUND - obstacle.top;
      ctx.fillStyle = '#b09470'; ctx.fillRect(x + 5, 0, 2, y); ctx.fillRect(x + w - 7, 0, 2, y);
      ctx.fillStyle = '#343932'; ctx.fillRect(x - 2, y - 2, w + 4, obstacle.top - obstacle.bottom + 4);
      ctx.fillStyle = '#738066'; ctx.fillRect(x, y, w, obstacle.top - obstacle.bottom);
      for (let py = y + 3; py < GROUND - obstacle.bottom; py += 10) {
        ctx.fillStyle = '#a5a484'; ctx.fillRect(x, py, w, 2);
        ctx.fillStyle = '#59674f'; ctx.fillRect(x + 3, py + 3, 3, 6);
      }
      ctx.fillStyle = '#dfbc7c'; ctx.fillRect(x - 2, GROUND - obstacle.bottom - 3, w + 4, 3);
    } else if (!obstacle.resolved && x > 145) {
      ctx.fillStyle = '#edc78e55';
      ctx.fillRect(x, GROUND - 3, 2, 3); ctx.fillRect(x + 6, GROUND - 3, 2, 3);
    }
  }
  let action = frame?.action ?? 'stand';
  const age = (frame?.action_age ?? 0) + interpolation * (frame?.pace ?? 1);
  const jumpDuration = frame?.jump_duration ?? 1.5;
  if (action === 'jump' && age >= jumpDuration) action = 'stand';
  const progress = age / jumpDuration;
  const bottom = action === 'jump' && age >= 0 ? 264 * progress * (1 - progress) : 0;
  ctx.fillStyle = '#0e122780'; ctx.fillRect(116, GROUND - 2, 33, 3);
  courier(ctx, 132, GROUND - bottom, action, time, frame?.hit ?? false);
  if (frame?.hit) { ctx.fillStyle = '#f35d6018'; ctx.fillRect(0, 0, 640, 360); }
}
