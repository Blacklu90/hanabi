// Quiz centre (start), runner (answer one at a time; the server checks every answer) and results.
import { $, $$, api, reward, sparks, toast } from './app.js';

async function start(body, errEl, btn) {
  btn?.classList.add('is-busy');
  if (errEl) errEl.hidden = true;
  try {
    const r = await api('/api/quiz/start', body);
    location.href = r.url;
  } catch (e) {
    btn?.classList.remove('is-busy');
    if (errEl) { errEl.textContent = e.message; errEl.hidden = false; errEl.scrollIntoView({ block: 'nearest' }); } else toast(e.message, 'err', 4000);
  }
}

// ------------------------------------------------------------ centre
const form = $('[data-quiz-form]');
if (form) {
  form.addEventListener('click', (e) => {
    const b = e.target.closest('[data-kind]');
    if (!b) return;
    const fd = new FormData(form);
    start({ kind: b.dataset.kind, mode: fd.get('mode'), pool: fd.get('pool'), grade: +fd.get('grade') || 0 }, $('[data-quiz-err]'), b);
  });
}

// ------------------------------------------------------------ results
const again = $('[data-again]');
if (again) again.addEventListener('click', () => start({ ...JSON.parse(again.dataset.again), pool: 'learned' }, $('[data-quiz-err]'), again));

// ------------------------------------------------------------ runner
const run = $('[data-quiz-run]');
if (run) {
  const qs = JSON.parse($('#quiz-data').textContent);
  const id = run.dataset.id, mode = run.dataset.mode;
  const timed = run.dataset.remaining !== undefined;
  const el = {
    prompt: $('[data-qprompt]', run), sub: $('[data-qsub]', run), opts: $('[data-opts]', run),
    fb: $('[data-fb]', run), next: $('[data-nextq]', run), prog: $('[data-progress]', run), count: $('[data-qcount]', run), clock: $('[data-clock]', run),
  };
  let i = +run.dataset.start || 0, locked = false, correct = 0, finishing = false;
  const deadline = timed ? Date.now() + (+run.dataset.remaining) * 1000 : null;

  function render() {
    const q = qs[i];
    locked = false;
    el.fb.className = 'feedback'; el.fb.textContent = '';
    el.next.hidden = true;
    el.prompt.className = 'glyph' + ({ text: ' text', sentence: ' sentence' }[q.prompt_kind] || (q.prompt.length > 2 ? ' word' : ''));
    el.prompt.textContent = q.prompt;
    el.sub.textContent = q.sub || '';
    const jpOpts = q.options.every(o => /^[぀-ヿ一-鿿々ー＿]+$/.test(o));
    el.opts.className = 'opts' + (q.options.some(o => o.length > 18) ? ' long' : '');
    el.opts.replaceChildren(...q.options.map((o, n) => {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'btn opt' + (jpOpts ? ' jp-opt' : ''); b.dataset.n = n;
      if (!jpOpts) { const k = document.createElement('span'); k.className = 'k'; k.textContent = n + 1; b.append(k); }
      b.append(o);
      b.setAttribute('aria-label', `${n + 1}: ${o}`);
      return b;
    }));
    el.count.textContent = timed ? `${correct} ✓` : `${i + 1}/${qs.length}`;
    if (!timed) el.prog.style.width = `${(100 * i) / qs.length}%`;
  }

  async function answer(n) {
    if (locked || finishing) return;
    locked = true;
    const btns = $$('.opt', el.opts);
    btns[n]?.classList.add('is-busy');
    let r;
    try { r = await api(`/api/quiz/${id}/answer`, { idx: i, choice: n }); }
    catch (e) {
      btns[n]?.classList.remove('is-busy');
      if (e.status === 409) { finish(); return; }
      toast(e.message, 'err'); locked = false; return;
    }
    btns[n]?.classList.remove('is-busy');
    if (r.expired) { finish(); return; }
    btns.forEach((b, k) => {
      if (k === r.answer) b.classList.add('right');
      else if (k === n) b.classList.add('wrong');
      else b.classList.add('dim');
      b.setAttribute('aria-disabled', 'true');
    });
    if (r.correct) { correct++; el.fb.textContent = 'Correct ✓'; el.fb.className = 'feedback show ok'; }
    else { el.fb.textContent = `✗ ${r.explain}`; el.fb.className = 'feedback show no'; }
    i++;
    if (i >= qs.length) { setTimeout(finish, r.correct ? 500 : 1400); return; }
    if (timed) { setTimeout(render, r.correct ? 220 : 900); return; }
    if (r.correct) setTimeout(render, 650);
    else { el.next.hidden = false; el.next.focus(); }
  }

  async function finish() {
    if (finishing) return;
    finishing = true;
    try {
      const r = await api('/api/quiz/submit', { id });
      if (r.passed) sparks();
      reward(r);
      setTimeout(() => { location.href = r.url; }, r.achievements?.length ? 900 : 150);
    } catch (e) { toast(e.message, 'err'); finishing = false; }
  }

  function tick() {
    const left = Math.max(0, deadline - Date.now());
    el.clock.textContent = `${Math.ceil(left / 1000)}s`;
    el.clock.classList.toggle('low', left < 10000);
    el.prog.style.width = `${100 * (1 - left / (+run.dataset.remaining * 1000 || 1))}%`;
    if (left <= 0) { locked = true; finish(); return; }
    requestAnimationFrame(() => setTimeout(tick, 200));
  }

  el.opts.addEventListener('click', (e) => { const b = e.target.closest('.opt'); if (b) answer(+b.dataset.n); });
  el.next.addEventListener('click', render);
  document.addEventListener('keydown', (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (/^[1-4]$/.test(e.key)) { e.preventDefault(); answer(+e.key - 1); }
    else if (e.key === 'Enter' && !el.next.hidden) { e.preventDefault(); render(); }
  });
  if (i >= qs.length) finish();
  else { render(); if (timed) tick(); }
}
