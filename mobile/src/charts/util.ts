/** Pure SVG path / scale helpers shared by every chart. */

export function extent(data: number[]): [number, number] {
  let mn = Infinity;
  let mx = -Infinity;
  for (const v of data) {
    if (!isFinite(v)) continue;
    if (v < mn) mn = v;
    if (v > mx) mx = v;
  }
  if (!isFinite(mn) || !isFinite(mx)) return [0, 1];
  if (mn === mx) return [mn - Math.abs(mn || 1) * 0.01, mx + Math.abs(mx || 1) * 0.01];
  return [mn, mx];
}

export type Pt = readonly [number, number];

export function linePath(pts: readonly Pt[]): string {
  if (!pts.length) return '';
  return pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(2)},${p[1].toFixed(2)}`).join(' ');
}

/** Catmull-Rom → cubic bézier smoothing for premium curve quality. */
export function smoothPath(pts: readonly Pt[]): string {
  if (pts.length < 3) return linePath(pts);
  let d = `M${pts[0][0].toFixed(2)},${pts[0][1].toFixed(2)}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] ?? pts[i];
    const p1 = pts[i];
    const p2 = pts[i + 1];
    const p3 = pts[i + 2] ?? p2;
    const cp1x = p1[0] + (p2[0] - p0[0]) / 6;
    const cp1y = p1[1] + (p2[1] - p0[1]) / 6;
    const cp2x = p2[0] - (p3[0] - p1[0]) / 6;
    const cp2y = p2[1] - (p3[1] - p1[1]) / 6;
    d += ` C${cp1x.toFixed(2)},${cp1y.toFixed(2)} ${cp2x.toFixed(2)},${cp2y.toFixed(2)} ${p2[0].toFixed(2)},${p2[1].toFixed(2)}`;
  }
  return d;
}

export function clampIndex(i: number, len: number): number {
  return Math.max(0, Math.min(len - 1, i));
}
