// Card browser: filter/sort/paginate on the server, select rows, bulk actions.
import { $, $$, ago, api, toast } from './app.js';

const form = $('[data-bfilters]'), body = $('[data-brows]'), pager = $('[data-bpager]'), count = $('[data-bcount]');
const selEl = $('[data-bsel]'), allBox = $('[data-all]'), moveSel = $('[data-move]');
const selected = new Set();
let page = 1, timer = null, ctrl = null;

const url = new URL(location.href);
for (const [k, v] of url.searchParams) {
  const f = form.elements[k];
  if (f) { if (f.type === 'checkbox') f.checked = v === '1'; else f.value = v; }
}

function params() {
  const p = new URLSearchParams();
  for (const el of form.elements) {
    if (!el.name) continue;
    if (el.type === 'checkbox') { if (el.checked) p.set(el.name, '1'); } else if (el.value && el.value !== '0') p.set(el.name, el.value.trim());
  }
  if (page > 1) p.set('page', page);
  return p;
}

const STATE_LABEL = { new: 'New', learning: 'Learning', review: 'Review', mastered: 'Mastered', suspended: 'Suspended', buried: 'Buried' };
function cell(text, cls = '') { const td = document.createElement('td'); td.textContent = text; if (cls) td.className = cls; return td; }

function row(it) {
  const tr = document.createElement('tr');
  tr.dataset.id = it.id;
  const cb = document.createElement('input'); cb.type = 'checkbox'; cb.checked = selected.has(it.id); cb.setAttribute('aria-label', `Select ${it.front}`);
  cb.addEventListener('change', () => { cb.checked ? selected.add(it.id) : selected.delete(it.id); updateSel(); });
  const td0 = document.createElement('td'); td0.append(cb);
  const front = document.createElement('td');
  const a = document.createElement('a');
  a.textContent = it.front.length > 40 ? it.front.slice(0, 40) + '…' : it.front;
  a.className = it.track === 'card' ? '' : 'jp b-front';
  a.href = it.track === 'kanji' ? `/kanji/${encodeURIComponent(it.item)}` : it.track === 'dict' ? `/dictionary?q=${encodeURIComponent(it.front)}` : '#';
  if (it.track === 'card') a.addEventListener('click', (e) => { e.preventDefault(); toast(it.answer, '', 5000); });
  front.append(a);
  if (it.has_note) front.append(Object.assign(document.createElement('span'), { className: 'tiny muted', textContent: ' ✎', title: 'Has your notes' }));
  const st = document.createElement('td');
  st.append(Object.assign(document.createElement('span'), { className: `pill st-${it.state}`, textContent: STATE_LABEL[it.state] || it.state }));
  const due = it.state === 'new' ? '—' : (it.due_at <= Date.now() / 1000 ? 'now' : ago(it.due_at));
  tr.append(td0, front, cell(it.answer, 'small'), cell(it.deck || '—', 'small hide-sm'), st, cell(due, 'small nowrap'),
    cell(it.interval, 'num hide-sm'), cell(it.reviews ? `${it.ease}%` : '—', 'num hide-sm'), cell(it.lapses, 'num hide-sm'));
  return tr;
}

function updateSel() {
  selEl.textContent = `${selected.size} selected`;
  for (const b of $$('[data-bulk-act]')) b.disabled = !selected.size;
  moveSel.disabled = !selected.size;
  const boxes = $$('tbody input[type=checkbox]', body.parentElement);
  allBox.checked = boxes.length > 0 && boxes.every(b => b.checked);
}

async function load(push = false) {
  const qs = params().toString();
  history[push ? 'pushState' : 'replaceState'](null, '', qs ? `?${qs}` : location.pathname);
  ctrl?.abort(); ctrl = new AbortController();
  try {
    const res = await fetch(`/api/cards?${qs}`, { signal: ctrl.signal, headers: { Accept: 'application/json' } });
    const d = await res.json();
    if (!d.ok) throw new Error(d.error);
    count.textContent = `${d.total.toLocaleString()} card${d.total === 1 ? '' : 's'}`;
    if (!d.items.length) {
      body.innerHTML = '<tr><td colspan="9" class="empty">No cards match. Add kanji to a deck from the Kanji library or a kanji page.</td></tr>';
    } else body.replaceChildren(...d.items.map(row));
    pager.replaceChildren();
    if (d.pages > 1) {
      const mk = (label, p, dis) => { const b = document.createElement('button'); b.type = 'button'; b.className = 'btn sm'; b.textContent = label; b.disabled = dis; b.onclick = () => { page = p; load(true); }; return b; };
      pager.append(mk('← Prev', d.page - 1, d.page <= 1), Object.assign(document.createElement('span'), { className: 'small muted', textContent: `${d.page} / ${d.pages}` }), mk('Next →', d.page + 1, d.page >= d.pages));
    }
    updateSel();
  } catch (e) { if (e.name !== 'AbortError') count.textContent = `Couldn't load cards: ${e.message}`; }
}

form.addEventListener('input', (e) => { page = 1; clearTimeout(timer); timer = setTimeout(() => load(false), e.target.type === 'search' ? 150 : 0); });
form.addEventListener('submit', (e) => e.preventDefault());
allBox.addEventListener('change', () => {
  for (const tr of $$('tr[data-id]', body)) {
    const id = +tr.dataset.id, cb = tr.querySelector('input');
    cb.checked = allBox.checked;
    allBox.checked ? selected.add(id) : selected.delete(id);
  }
  updateSel();
});

async function bulk(action, extra = '') {
  const ids = [...selected];
  if (action === 'delete' && !confirm(`Delete ${ids.length} card${ids.length === 1 ? '' : 's'} and their review history? This can't be undone.`)) return;
  if (action === 'forget' && !confirm(`Reset ${ids.length} card${ids.length === 1 ? '' : 's'} to new? Their schedule starts over.`)) return;
  try {
    const r = await api(`/api/cards/${action}${extra}`, { ids });
    toast(`${r.count} card${r.count === 1 ? '' : 's'} updated ✓`);
    selected.clear();
    load(false);
  } catch (e) { toast(e.message, 'err'); }
}
for (const b of $$('[data-bulk-act]')) b.addEventListener('click', () => bulk(b.dataset.bulkAct));
moveSel.addEventListener('change', () => { if (moveSel.value) { bulk('move', `?deck_id=${moveSel.value}`); moveSel.value = ''; } });
addEventListener('popstate', () => location.reload());
load(false);
