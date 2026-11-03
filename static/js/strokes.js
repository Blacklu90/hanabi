// KanjiVG stroke-order player. Loads an SVG on demand and animates its strokes.
import { reduced } from './app.js';

const cache = new Map();
async function fetchSvg(url) {
  if (!cache.has(url)) cache.set(url, fetch(url).then(r => (r.ok ? r.text() : Promise.reject(new Error('missing')))));
  return cache.get(url);
}

/** Copy only <path d> and <text> nodes from a KanjiVG file (never inject foreign markup). */
export async function loadInto(box, { numbers = true } = {}) {
  const url = box.dataset.strokes || box.dataset.src;
  let txt;
  try { txt = await fetchSvg(url); } catch {
    box.innerHTML = '<div class="missing small">No stroke-order diagram for this character.</div>';
    return null;
  }
  const doc = new DOMParser().parseFromString(txt, 'image/svg+xml');
  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', doc.documentElement.getAttribute('viewBox') || '0 0 109 109');
  svg.setAttribute('aria-hidden', 'true');
  const paths = [];
  for (const p of doc.querySelectorAll('path[d]')) {
    if (!/-s\d+$/.test(p.getAttribute('id') || '')) continue;
    const n = document.createElementNS(NS, 'path'); n.setAttribute('d', p.getAttribute('d')); svg.append(n); paths.push(n);
  }
  if (numbers) for (const t of doc.querySelectorAll('text')) {
    const n = document.createElementNS(NS, 'text'); n.textContent = t.textContent;
    const m = (t.getAttribute('transform') || '').match(/matrix\(1 0 0 1 ([\d.]+) ([\d.]+)\)/);
    if (m) { n.setAttribute('x', m[1]); n.setAttribute('y', m[2]); }
    svg.append(n);
  }
  box.replaceChildren(svg);
  return makePlayer(paths);
}

function makePlayer(paths) {
  let step = paths.length, timer = null;
  const lens = paths.map(p => p.getTotalLength?.() || 100);
  const show = (n, animateLast = false) => {
    step = n;
    paths.forEach((p, i) => {
      p.classList.toggle('pending', i >= n);
      p.classList.remove('current');
      p.style.transition = 'none'; p.style.strokeDasharray = ''; p.style.strokeDashoffset = '';
    });
    if (animateLast && n > 0 && !reduced()) {
      const p = paths[n - 1], L = lens[n - 1];
      p.classList.add('current');
      p.style.strokeDasharray = `${L} ${L}`; p.style.strokeDashoffset = L;
      p.getBoundingClientRect();
      p.style.transition = `stroke-dashoffset ${Math.max(220, L * 6)}ms ease-out`;
      p.style.strokeDashoffset = 0;
    } else if (n > 0) paths[n - 1].classList.add('current');
    if (n === paths.length) setTimeout(() => paths.forEach(p => p.classList.remove('current')), 500);
  };
  const stop = () => { clearTimeout(timer); timer = null; };
  return {
    count: paths.length,
    reset() { stop(); show(0); },
    full() { stop(); show(paths.length); },
    step() { stop(); show(step >= paths.length ? 1 : step + 1, true); },
    play() {
      stop(); show(0);
      const next = () => {
        if (step >= paths.length) return;
        show(step + 1, true);
        timer = setTimeout(next, reduced() ? 350 : Math.max(380, lens[step - 1] * 6 + 140));
      };
      timer = setTimeout(next, 150);
    },
  };
}

/** Wire every [data-strokes] box with sibling play/step/reset buttons inside `scope`. */
export async function wireStrokes(scope = document) {
  for (const box of scope.querySelectorAll('[data-strokes]')) {
    const root = box.closest('[data-step], .card, [data-writing], .row') || scope;
    const player = await loadInto(box);
    if (!player) continue;
    const ctl = box.closest('.card, [data-step]') || root;
    ctl.querySelector('[data-play]')?.addEventListener('click', () => player.play());
    ctl.querySelector('[data-step-stroke]')?.addEventListener('click', () => player.step());
    ctl.querySelector('[data-reset-stroke]')?.addEventListener('click', () => player.reset());
    const nums = ctl.querySelector('[data-nums]');
    nums?.addEventListener('click', () => { const on = nums.getAttribute('aria-pressed') !== 'true'; nums.setAttribute('aria-pressed', on); box.classList.toggle('no-nums', !on); });
    box._player = player;
  }
}
