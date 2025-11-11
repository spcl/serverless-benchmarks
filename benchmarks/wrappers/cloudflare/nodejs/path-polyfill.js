/**
 * Minimal POSIX-like path.resolve polyfill for Cloudflare Workers / browser.
 * Always returns an absolute path starting with '/'.
 * Does not use process.cwd(); root '/' is the base.
 */

function normalizeSegments(segments) {
  const out = [];
  for (const seg of segments) {
    if (!seg || seg === '.') continue;
    if (seg === '..') {
      if (out.length && out[out.length - 1] !== '..') out.pop();
      continue;
    }
    out.push(seg);
  }
  return out;
}

/**
 * Resolve path segments into an absolute path.
 * @param  {...string} input
 * @returns {string}
 */
export function resolve(...input) {
  if (!input.length) return '/';
  let absoluteFound = false;
  const segments = [];

  for (let i = input.length - 1; i >= 0; i--) {
    let part = String(input[i]);
    if (part === '') continue;
    // Normalize backslashes to forward slashes (basic win compatibility)
    part = part.replace(/\\/g, '/');

    if (part[0] === '/') {
      absoluteFound = true;
      part = part.slice(1); // drop leading '/' to just collect segments
    }
    const split = part.split('/');
    for (let j = split.length - 1; j >= 0; j--) {
      const seg = split[j];
      if (seg) segments.push(seg);
    }
    if (absoluteFound) break;
  }

  const normalized = normalizeSegments(segments.reverse());
  return '/' + normalized.join('/');
}

// Optional convenience exports similar to Node's path.posix interface
const path = { resolve };
export default path;