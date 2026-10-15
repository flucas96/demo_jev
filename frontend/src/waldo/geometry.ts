import type { CSSProperties } from 'react';
import type { Box } from './types';

/** Keep annotation overlays aligned with the actual image rather than its container. */
export function boxStyle(box: Box): CSSProperties {
  return { left: `${box.left * 100}%`, top: `${box.top * 100}%`, width: `${(box.right - box.left) * 100}%`, height: `${(box.bottom - box.top) * 100}%` };
}

/** Mirror the server's visible tolerance border for a draft annotation. */
export function paddedBox(box: Box, padding: number): Box {
  const dx = (box.right - box.left) * padding;
  const dy = (box.bottom - box.top) * padding;
  return { left: Math.max(0, box.left - dx), right: Math.min(1, box.right + dx), top: Math.max(0, box.top - dy), bottom: Math.min(1, box.bottom + dy) };
}
