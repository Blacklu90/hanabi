// Kanji library: debounced search, cancellable requests, small in-memory cache, URL kept in sync.
import { $, api, get, reward, toast } from './app.js';

const form = $('[data-kfilters]');
const grid = $('[data-kgrid]'), pager = $('[data-kpager]'), count = $('[data-kcount]');
const cache = new Map();
let ctrl = null, page = 1, timer = null;

// Restore filters from the URL (so links like /kanji?radical=72 and back/forward work).
const url = new URL(location.href);
for (const [k, v] of url.searchParams) if (form.elements[k]) form.elements[k].value = v;
page = +url.searchParams.get('page') || 1;

function params() {
  const p = new URLSearchParams();
  for (const el of form.elements) if (el.name && el.value && el.value !== '0') p.set(el.name, el.value.trim());
  if (page > 1) p.set('page', page);
  return p;
}

function cell(k) {
  const a = document.createElement('a');
  a.className = 'kcell' + (k.state ? ` ${k.state}` : '');
  a.href = `/kanji/${encodeURIComponent(k.char)}`;
  a.title = `${k.meaning} · ${k.strokes} strokes`;
  const b = document.createElement('b'); b.lang = 'ja'; b.textContent = k.char;
  const m = document.createElement('span'); m.className = 'm'; m.textContent = k.meaning;
  const r = document.createElement('span'); r.className = 'r'; r.textContent = [k.on, k.kun].filter(Boolean).join(' · ');
  a.append(b, m, r);
  return a;
}

function draw(d) {
  grid.setAttribute('aria-busy', 'false');
  count.textContent = d.total ? `${d.total.toLocaleString()} kanji · page ${d.page} of ${d.pages}` : '';
  if (!d.items.length) {
    const e = document.createElement('div'); e.className = 'empty'; e.style.gridColumn = '1/-1';
    e.innerHTML = '<span class="big-glyph">無</span>No kanji match. Try fewer filters, a meaning in English, or a reading like “にち”.';
    grid.replaceChildren(e); pager.replaceChildren(); return;
  }
  grid.replaceChildren(...d.items.map(cell));
  pager.replaceChildren();
  if (d.pages > 1) {
    const mk = (label, p, dis) => { const b = document.createElement('button'); b.type = 'button'; b.className = 'btn sm'; b.textContent = label; b.disabled = dis; b.onclick = () => { page = p; load(true); scrollTo({ top: 0 }); }; return b; };
    const info = document.createElement('span'); info.className = 'small muted'; info.textContent = `${d.page} / ${d.pages}`;
    pager.append(mk('← Prev', d.page - 1, d.page <= 1), info, mk('Next →', d.page + 1, d.page >= d.pages));
  }
}

async function load(push = false) {
  const p = params();
  const qs = p.toString();
  history[push ? 'pushState' : 'replaceState'](null, '', qs ? `?${qs}` : location.pathname);
  if (cache.has(qs)) { draw(cache.get(qs)); prefetchNext(cache.get(qs)); return; }
  ctrl?.abort();
  ctrl = new AbortController();
  grid.setAttribute('aria-busy', 'true');
  try {
    const res = await fetch(`/api/kanji/search?${qs}`, { signal: ctrl.signal, headers: { Accept: 'application/json' } });
    const d = await res.json();
    if (!d.ok) throw new Error(d.error);
    cache.set(qs, d);
    draw(d);
    prefetchNext(d);
  } catch (e) {
    if (e.name !== 'AbortError') { count.textContent = 'Search failed. Check your connection and try again.'; }
  }
}

// Fetch the next page quietly so "Next" is instant.
function prefetchNext(d) {
  if (d.page >= d.pages) return;
  const p = params(); p.set('page', d.page + 1);
  const qs = p.toString();
  if (cache.has(qs)) return;
  get(`/api/kanji/search?${qs}`).then(r => cache.set(qs, r)).catch(() => {});
}

form.addEventListener('input', (e) => {
  page = 1;
  clearTimeout(timer);
  timer = setTimeout(() => load(false), e.target.type === 'search' ? 140 : 0);
});
form.addEventListener('submit', (e) => { e.preventDefault(); page = 1; load(true); });
addEventListener('popstate', () => {
  const u = new URL(location.href);
  for (const el of form.elements) if (el.name) el.value = u.searchParams.get(el.name) || (el.tagName === 'SELECT' ? el.options[0].value : '');
  page = +u.searchParams.get('page') || 1;
  load(false);
});
load(false);

// Add every kanji matching the current search/filters to a deck (as new cards, in the current sort order).
$('[data-bulk-add]')?.addEventListener('click', async (e) => {
  const btn = e.currentTarget, sel = $('[data-bulk-deck]');
  let deck = sel.value;
  try {
    const p = params(); p.delete('page'); p.set('all', '1');
    const { chars } = await get(`/api/kanji/search?${p}`);
    if (!chars.length) { toast('No kanji to add. Change the filters first.'); return; }
    let name = null;
    if (deck === 'new') {
      name = prompt('Name for the new deck:', 'My kanji deck');
      if (!name) return;
    }
    if (!confirm(`Add ${chars.length} kanji to ${name ? `a new deck “${name}”` : 'this deck'} as new cards?`)) return;
    if (name) deck = (await api('/api/decks', { name, new_per_day: 10, max_reviews: 200 })).id;
    btn.classList.add('is-busy');
    const r = await api(`/api/decks/${deck}/kanji`, { chars });
    toast(`Added ${r.added} kanji${r.skipped ? ` (${r.skipped} were already in a deck)` : ''} ✓`, 'gold', 4000);
    reward(r);
    cache.clear(); load(false);
  } catch (err) { toast(err.message, 'err'); }
  btn.classList.remove('is-busy');
});
