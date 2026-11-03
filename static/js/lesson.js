// Lesson: meet each character one at a time, quick self-check, then complete.
import { $, $$, api, reward, sparks, toast } from './app.js';
import { wireStrokes } from './strokes.js';

const root = $('[data-lesson]');
const data = JSON.parse($('#lesson-data').textContent);
const steps = $$('[data-step]', root);
const prog = $('[data-progress]', root), label = $('[data-step-label]', root);
const prevB = $('[data-prev]', root), nextB = $('[data-next]', root);
const check = $('[data-check]', root), finish = $('[data-finish]', root), nav = $('[data-nav]', root);
const SPECIAL = ['ッ', 'ー'];
let i = 0, phase = 'meet', qi = 0, order = [], answered = false, waiting = false;
const nextHint = $('[data-check-next]', root);
nextHint.addEventListener('click', () => { if (waiting) nextQ(); });
const total = steps.length + 1;

wireStrokes(root).then(() => steps[0]?.querySelector('[data-strokes]')?._player?.play());

function setProgress(n) {
  const pct = Math.round((100 * n) / total);
  prog.style.width = `${pct}%`;
  prog.parentElement.setAttribute('aria-valuenow', pct);
}

function showStep(n) {
  steps.forEach((s, k) => { s.hidden = k !== n; });
  i = n;
  prevB.disabled = n === 0;
  label.textContent = `${n + 1}/${steps.length}`;
  nextB.textContent = n === steps.length - 1 ? 'Quick check →' : 'Next →';
  setProgress(n);
  steps[n].querySelector('[data-strokes]')?._player?.play();
}

function shuffle(a) { return a.map(v => [Math.random(), v]).sort((x, y) => x[0] - y[0]).map(x => x[1]); }

function startCheck() {
  phase = 'check';
  steps.forEach(s => { s.hidden = true; });
  check.hidden = false; prevB.hidden = true; nextB.hidden = true;
  order = shuffle(data.chars.map((c, k) => k).filter(k => !SPECIAL.includes(data.chars[k])));
  label.textContent = 'Check';
  setProgress(steps.length);
  if (order.length === 0) { complete(); return; }
  qi = 0;
  ask();
}

function ask() {
  answered = false;
  const k = order[qi], right = data.romaji[k];
  $('[data-check-glyph]', check).textContent = data.chars[k];
  const pool = shuffle([...new Set(data.pool.filter(r => r !== right))]).slice(0, 3);
  const opts = shuffle([...pool, right]);
  const box = $('[data-check-opts]', check);
  box.replaceChildren();
  opts.forEach((o, n) => {
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'btn opt'; b.dataset.v = o;
    const key = document.createElement('span'); key.className = 'k'; key.textContent = n + 1;
    b.append(key, o);
    b.addEventListener('click', () => pick(b, o === right, right));
    box.append(b);
  });
  $('[data-check-fb]', check).className = 'feedback';
}

function pick(b, ok, right) {
  if (answered) return;
  answered = true;
  const fb = $('[data-check-fb]', check);
  $$('.opt', check).forEach(x => {
    if (x.dataset.v === right) x.classList.add('right');
    else if (x !== b) x.classList.add('dim');
  });
  if (ok) {
    fb.textContent = 'Yes! ✓'; fb.className = 'feedback show ok';
  } else {
    b.classList.add('wrong');
    fb.textContent = `Not quite. It's “${right}”.`;
    const hook = data.hooks[order[qi]];
    if (hook) {
      const p = document.createElement('p'); p.className = 'hook';
      const ic = document.createElement('span'); ic.className = 'hook-ic'; ic.textContent = '💡';
      const t = document.createElement('span'); t.textContent = hook;
      p.append(ic, t); fb.append(p);
    }
    fb.className = 'feedback show no';
  }
  // A wrong answer waits for a tap/key so there's time to read the hook.
  if (ok) setTimeout(nextQ, 650);
  else { waiting = true; nextHint.hidden = false; }
}

function nextQ() {
  waiting = false; nextHint.hidden = true;
  qi++;
  if (qi < order.length) ask(); else complete();
}

async function complete() {
  phase = 'done';
  check.hidden = true; nav.hidden = true; finish.hidden = false;
  setProgress(total); label.textContent = '✓';
  try {
    const r = await api('/api/lesson/complete', { lesson: root.dataset.slug });
    if (!r.first) $('[data-finish-msg]', finish).textContent = 'You already finished this lesson. Going over it again still helps.';
    sparks();
    reward(r);
  } catch (e) { toast(e.message, 'err'); }
}

prevB.addEventListener('click', () => { if (i > 0) showStep(i - 1); });
nextB.addEventListener('click', () => { if (i < steps.length - 1) showStep(i + 1); else startCheck(); });
document.addEventListener('keydown', (e) => {
  if (e.target.closest('input,textarea')) return;
  if (phase === 'meet') {
    if (e.key === 'ArrowRight' || e.key === 'Enter') { e.preventDefault(); nextB.click(); }
    else if (e.key === 'ArrowLeft') prevB.click();
  } else if (phase === 'check' && waiting && (e.key === 'Enter' || e.key === ' ')) {
    e.preventDefault(); nextQ();
  } else if (phase === 'check' && /^[1-4]$/.test(e.key)) {
    $$('.opt', check)[+e.key - 1]?.click();
  }
});
showStep(0);
