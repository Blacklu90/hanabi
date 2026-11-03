// Vocabulary: instant client-side search + category filter (all words are already on the page).
import { $, $$, api, reward, toast } from './app.js';

const box = $('[data-vocab]');
const track = box.dataset.track;
const cards = $$('[data-vgrid] [data-word]');
const q = $('[data-q]', box), countEl = $('[data-count]', box), empty = $('[data-empty]');
let cat = '';

const norm = (s) => s.toLowerCase().trim();
function apply() {
  const t = norm(q.value);
  let n = 0;
  for (const c of cards) {
    const show = (!cat || c.dataset.cat === cat) && (!t || c.dataset.s.includes(t));
    c.hidden = !show;
    if (show) n++;
  }
  countEl.textContent = `${n} word${n === 1 ? '' : 's'}`;
  empty.hidden = n > 0;
}
let tm;
q.addEventListener('input', () => { clearTimeout(tm); tm = setTimeout(apply, 60); });
box.addEventListener('click', (e) => {
  const chip = e.target.closest('[data-cat]');
  if (chip) {
    cat = chip.dataset.cat;
    $$('[data-cat]', box).forEach(c => c.setAttribute('aria-pressed', c === chip));
    apply();
  }
});

async function add(items, btns) {
  btns.forEach(b => b.classList.add('is-busy'));
  try {
    const r = await api('/api/srs/add', { track, items });
    btns.forEach(b => { b.classList.remove('is-busy'); b.disabled = true; b.textContent = '✓ In reviews'; });
    toast(r.added ? `Added ${r.added} word${r.added === 1 ? '' : 's'}. They're due now.` : 'Already in your reviews.');
    reward(r);
  } catch (e) { btns.forEach(b => b.classList.remove('is-busy')); toast(e.message, 'err'); }
}
document.addEventListener('click', (e) => {
  const b = e.target.closest('[data-add]');
  if (b && !b.disabled) add([b.dataset.add], [b]);
});
$('[data-add-visible]', box).addEventListener('click', () => {
  const vis = cards.filter(c => !c.hidden).map(c => c.querySelector('[data-add]')).filter(b => !b.disabled);
  if (!vis.length) { toast('Everything shown is already in your reviews.'); return; }
  if (vis.length > 30 && !confirm(`Add ${vis.length} words at once? Smaller batches are easier to keep up with.`)) return;
  add(vis.map(b => b.dataset.add), vis);
});
