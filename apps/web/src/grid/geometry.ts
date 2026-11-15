// Pure index <-> pixel math for the virtualized grid. No DOM here, so it is unit-tested at 100k
// and 1M rows. Browsers cap the height of a scrollable element (measured in Firefox 160: 10,000,000 px
// lays out, 30,000,000 px does not), so the vertical scroll range is capped and scaled.

/** Largest scroll proxy height used. Safe for Firefox (~17.9M px) and Chrome (~33.5M px). */
export const MAX_PROXY_PX = 10_000_000;

export interface Axis {
  readonly count: number;
  readonly total: number;
  size(i: number): number;
  offset(i: number): number;
  /** Index of the item containing `offset` (clamped to [0, count-1]). */
  indexAt(offset: number): number;
}

export function uniformAxis(count: number, size: number): Axis {
  return {
    count,
    total: count * size,
    size: () => size,
    offset: (i) => i * size,
    indexAt: (o) => (count === 0 ? 0 : Math.min(count - 1, Math.max(0, Math.floor(o / size)))),
  };
}

/** Variable sizes with prefix sums (columns: up to 16,384 items). */
export function variableAxis(count: number, sizeOf: (i: number) => number): Axis {
  const prefix = new Float64Array(count + 1);
  for (let i = 0; i < count; i++) prefix[i + 1] = (prefix[i] ?? 0) + sizeOf(i);
  return {
    count,
    total: prefix[count] ?? 0,
    size: (i) => (prefix[i + 1] ?? 0) - (prefix[i] ?? 0),
    offset: (i) => prefix[Math.min(Math.max(i, 0), count)] ?? 0,
    indexAt: (o) => {
      if (count === 0) return 0;
      let lo = 0;
      let hi = count - 1;
      while (lo < hi) {
        const mid = (lo + hi + 1) >> 1;
        if ((prefix[mid] ?? 0) <= o) lo = mid;
        else hi = mid - 1;
      }
      return lo;
    },
  };
}

export interface IndexRange {
  first: number;
  last: number; // inclusive; last < first means empty
}

/** Items intersecting [start, start+viewport) plus `overscan` items on each side. */
export function visibleRange(axis: Axis, start: number, viewport: number, overscan: number): IndexRange {
  if (axis.count === 0 || viewport <= 0) return { first: 0, last: -1 };
  const first = Math.max(0, axis.indexAt(start) - overscan);
  const last = Math.min(axis.count - 1, axis.indexAt(start + viewport - 1) + overscan);
  return { first, last };
}

/**
 * Vertical scroll mapping. `contentPx` is the real height of all rows, `viewportPx` the visible
 * body height. When contentPx fits under MAX_PROXY_PX the mapping is the identity; otherwise the
 * scroller is `proxyPx` tall and scrollTop is scaled so that scrollTop = 0 shows the first row and
 * the maximum scrollTop shows the last row exactly.
 */
export interface Scroller {
  proxyPx: number;
  scale: number; // contentTop = scrollTop * scale
  scaled: boolean;
  toContent(scrollTop: number): number;
  toScroll(contentTop: number): number;
}

export function makeScroller(contentPx: number, viewportPx: number, maxProxy = MAX_PROXY_PX): Scroller {
  if (contentPx <= maxProxy || contentPx <= viewportPx) {
    return { proxyPx: contentPx, scale: 1, scaled: false, toContent: (s) => s, toScroll: (c) => c };
  }
  const proxyPx = maxProxy;
  const scale = (contentPx - viewportPx) / (proxyPx - viewportPx);
  return {
    proxyPx,
    scale,
    scaled: true,
    toContent: (s) => Math.min(Math.max(s, 0) * scale, contentPx - viewportPx),
    toScroll: (c) => Math.min(Math.max(c, 0) / scale, proxyPx - viewportPx),
  };
}

/** Column letters: 0 -> A, 25 -> Z, 26 -> AA. */
export function columnLetters(c: number): string {
  let n = c + 1;
  let out = "";
  while (n > 0) {
    const rem = (n - 1) % 26;
    out = String.fromCharCode(65 + rem) + out;
    n = Math.floor((n - 1) / 26);
  }
  return out;
}
