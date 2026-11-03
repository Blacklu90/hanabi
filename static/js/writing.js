// Writing practice canvas: pointer events (mouse, touch, stylus with pressure), undo, clear, guide, self-check.
import { $, api, reward, sparks, toast } from './app.js';
import { loadInto, wireStrokes } from './strokes.js';

const root = $('[data-writing]');
const box = $('[data-canvas-box]', root), canvas = $('[data-canvas]', root), guide = $('[data-guide]', root);
const ctx = canvas.getContext('2d');
const strokes = [];
let current = null;

loadInto(guide, { numbers: false }).then(p => p?.full());
wireStrokes(root);

function resize() {
  const r = canvas.getBoundingClientRect(), dpr = Math.min(devicePixelRatio || 1, 2);
  canvas.width = Math.round(r.width * dpr); canvas.height = Math.round(r.height * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  redraw();
}
function inkColor() { return getComputedStyle(document.documentElement).getPropertyValue('--ink').trim() || '#222'; }
function redraw() {
  const r = canvas.getBoundingClientRect();
  ctx.clearRect(0, 0, r.width, r.height);
  ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.strokeStyle = inkColor();
  const base = r.width / 32;
  for (const s of strokes) {
    for (let k = 1; k < s.length; k++) {
      ctx.lineWidth = base * (0.55 + 0.6 * (s[k].p || 0.5));
      ctx.beginPath(); ctx.moveTo(s[k - 1].x, s[k - 1].y); ctx.lineTo(s[k].x, s[k].y); ctx.stroke();
    }
    if (s.length === 1) { ctx.beginPath(); ctx.arc(s[0].x, s[0].y, base / 2, 0, Math.PI * 2); ctx.fillStyle = inkColor(); ctx.fill(); }
  }
}
function pt(e) { const r = canvas.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top, p: e.pointerType === 'pen' ? e.pressure : 0.5 }; }

canvas.addEventListener('pointerdown', (e) => {
  e.preventDefault();
  canvas.setPointerCapture(e.pointerId);
  current = [pt(e)]; strokes.push(current); redraw();
});
canvas.addEventListener('pointermove', (e) => {
  if (!current) return;
  for (const ce of (e.getCoalescedEvents?.() || [e])) current.push(pt(ce));
  redraw();
});
const end = () => { current = null; };
canvas.addEventListener('pointerup', end);
canvas.addEventListener('pointercancel', end);

$('[data-undo]', root).addEventListener('click', () => { strokes.pop(); redraw(); });
$('[data-clear]', root).addEventListener('click', () => { strokes.length = 0; redraw(); });
const tg = $('[data-toggle-guide]', root);
tg.addEventListener('click', () => {
  const hide = !box.classList.contains('noguide');
  box.classList.toggle('noguide', hide);
  tg.setAttribute('aria-pressed', String(!hide));
  tg.textContent = hide ? 'Show guide' : 'Hide guide';
});
const msg = $('[data-wmsg]', root);
$('[data-selfcheck]', root).addEventListener('click', async (e) => {
  if (!strokes.length) { msg.textContent = 'Draw the character first, then check it against the guide.'; return; }
  const btn = e.currentTarget; btn.classList.add('is-busy');
  try {
    const r = await api('/api/writing/complete', { track: root.dataset.track, item: root.dataset.item });
    msg.textContent = r.xp ? 'Nice brushwork! ✓ Try it again without the guide.' : 'Logged ✓ (XP for this character is once a day).';
    sparks(); reward(r, btn);
    const nxt = document.querySelector('.char-pick a[aria-current="true"]')?.nextElementSibling;
    if (nxt) msg.append(' ', Object.assign(document.createElement('a'), { href: nxt.href, textContent: `Next: ${nxt.textContent} →` }));
  } catch (err) { toast(err.message, 'err'); }
  btn.classList.remove('is-busy');
});
document.addEventListener('keydown', (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); strokes.pop(); redraw(); }
});
new ResizeObserver(resize).observe(canvas);
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', redraw);
