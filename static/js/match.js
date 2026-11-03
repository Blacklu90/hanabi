// Matching game: 6 pairs. The board comes from the server; the server checks the result and awards XP once.
import { $, $$, api, reward, sparks, toast } from './app.js';

const root = $('[data-match]');
const board = $('[data-board]', root), done = $('[data-mdone]', root);
const out = { time: $('[data-time]', root), moves: $('[data-moves]', root), matches: $('[data-matches]', root), misses: $('[data-misses]', root) };
let deck = 'hiragana', game = null, sel = null, moves = 0, misses = 0, matches = 0, t0 = 0, raf = 0, busy = false;

function update() { out.moves.textContent = moves; out.misses.textContent = misses; out.matches.textContent = matches; }
function clock() { out.time.textContent = ((performance.now() - t0) / 1000).toFixed(1); raf = requestAnimationFrame(clock); }

async function newGame() {
  cancelAnimationFrame(raf);
  done.hidden = true; board.hidden = false;
  sel = null; moves = misses = matches = 0; update(); out.time.textContent = '0.0';
  board.replaceChildren(...Array.from({ length: 12 }, () => Object.assign(document.createElement('div'), { className: 'mcard skeleton' })));
  try { game = await api('/api/game/start', { deck }); } catch (e) { toast(e.message, 'err'); return; }
  board.replaceChildren(...game.cards.map((c, k) => {
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'mcard' + (c.side === 'jp' ? ' jp' : '');
    b.textContent = c.text; b.dataset.k = k; b.lang = c.side === 'jp' ? 'ja' : 'en';
    return b;
  }));
  t0 = performance.now(); clock();
}

board.addEventListener('click', (e) => {
  const b = e.target.closest('.mcard'); if (!b || !game || busy || b.classList.contains('done')) return;
  const c = game.cards[+b.dataset.k];
  if (!sel) { sel = b; b.classList.add('sel'); b.setAttribute('aria-pressed', 'true'); return; }
  if (sel === b) { b.classList.remove('sel'); b.removeAttribute('aria-pressed'); sel = null; return; }
  const s = game.cards[+sel.dataset.k];
  moves++;
  if (s.pair === c.pair && s.side !== c.side) {
    [sel, b].forEach(x => { x.classList.remove('sel'); x.classList.add('done'); x.disabled = true; });
    matches++;
    const r = b.getBoundingClientRect(); sparks(r.left + r.width / 2, r.top + r.height / 2, 8);
    sel = null; update();
    if (matches === 6) finish();
  } else {
    misses++; busy = true;
    const a = sel; [a, b].forEach(x => x.classList.add('miss'));
    setTimeout(() => { [a, b].forEach(x => x.classList.remove('miss', 'sel')); a.removeAttribute('aria-pressed'); busy = false; }, 550);
    sel = null; update();
  }
});

async function finish() {
  cancelAnimationFrame(raf);
  const secs = ((performance.now() - t0) / 1000).toFixed(1);
  try {
    const r = await api('/api/game/complete', { id: game.id, moves, misses });
    $('[data-mresult]', done).textContent = `${r.seconds}s · ${moves} moves · ${misses} miss${misses === 1 ? '' : 'es'} · +${r.xp} XP`;
    reward(r);
  } catch (e) { $('[data-mresult]', done).textContent = `${secs}s · ${moves} moves · ${e.message}`; }
  board.hidden = true; done.hidden = false; sparks();
}

root.addEventListener('click', (e) => {
  const d = e.target.closest('[data-deck]');
  if (d) { deck = d.dataset.deck; $$('[data-deck]', root).forEach(x => x.setAttribute('aria-pressed', x === d)); newGame(); }
  if (e.target.closest('[data-restart]')) newGame();
});
newGame();
