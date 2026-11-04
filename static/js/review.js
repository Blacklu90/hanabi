// Flashcard review (Anki-style): reveal, rate 1–4 (each button shows its next interval),
// undo the last answer, bury/suspend, and edit your own notes. The server schedules everything.
import { furigana, h, kanaNotes, kanaRows, kanjiRows } from './words-ui.js';
import { say, sayButton, stop as stopSay } from './speak.js';
import { $, $$, api, burstActive, reward, sparks, toast } from './app.js';

const root = $('[data-review]');
if (root) {
  const cards = JSON.parse($('#review-data').textContent);
  const practice = root.dataset.practice === '1';
  const practiceSet = cards.map(c => ({ ...c }));
  let rounds = 0, firstTry = 0;
  const el = {
    card: $('[data-card]', root), front: $('[data-front]', root), back: $('[data-back]', root), answer: $('[data-answer]', root),
    reading: $('[data-reading]', root), extra: $('[data-extra]', root), track: $('[data-track]', root), link: $('[data-link]', root),
    show: $('[data-show]', root), showWrap: $('[data-show-wrap]', root), rate: $('[data-rate]', root), prog: $('[data-progress]', root),
    count: $('[data-count]', root), done: $('[data-done]', root), undo: $('[data-undo]', root),
    hook: $('[data-hook]', root), hookText: $('[data-hook-text]', root), mine: $('[data-mine]', root), mineText: $('[data-mine-text]', root),
    frame: $('[data-anki-frame]', root), answerBox: $('[data-answer]', root),
  };
  const showRomaji = document.body.dataset.romaji !== '0';
  let i = 0, revealed = false, busy = false, done = 0, again = 0, finished = false;
  const history = [];  // [{review_id, index}] so Undo can step back

  // ---- imported Anki cards: shown in a sandboxed frame with the deck's own template, images and audio
  const autoplay = document.body.dataset.autoplay !== '0';
  const isDark = () => {
    const t = document.documentElement.dataset.theme;
    return t === 'dark' || (t === 'system' && matchMedia('(prefers-color-scheme: dark)').matches);
  };
  let frameObs = null;
  function frameDoc() { try { return el.frame.contentDocument; } catch { return null; } }
  function fitFrame() {
    const d = frameDoc();
    if (d?.documentElement) el.frame.style.height = `${Math.max(120, d.documentElement.scrollHeight)}px`;
  }
  function playSounds(list) {
    const queue = [...list];
    const next = () => {
      const a = queue.shift();
      if (!a) return;
      const btn = a.previousElementSibling;
      btn?.classList.add('playing');
      a.addEventListener('ended', () => { btn?.classList.remove('playing'); next(); }, { once: true });
      a.currentTime = 0;
      a.play().catch(() => { btn?.classList.remove('playing'); next(); });
    };
    next();
  }
  function stopSounds() {
    for (const a of frameDoc()?.querySelectorAll('audio') || []) { a.pause(); a.previousElementSibling?.classList.remove('playing'); }
  }
  function replay() { stopSounds(); playSounds(frameDoc()?.querySelectorAll('audio') || []); }
  function showFrame(url) {
    stopSounds();
    el.frame.onload = () => {
      fitFrame();
      frameObs?.disconnect();
      const d = frameDoc();
      d?.body?.style.setProperty('--hb-accent', getComputedStyle(document.documentElement).getPropertyValue('--accent').trim());
      if (d?.body && 'ResizeObserver' in window) { frameObs = new ResizeObserver(fitFrame); frameObs.observe(d.body); }
      for (const img of d?.images || []) img.addEventListener('load', fitFrame);
      // Round ▶ buttons (like Anki): Shuinkan handles the click, since the card frame itself can't run scripts.
      d?.addEventListener('click', (ev) => {
        const b = ev.target.closest?.('.replay-button');
        if (!b) return;
        ev.preventDefault();
        stopSounds();
        playSounds([b.nextElementSibling].filter(x => x?.tagName === 'AUDIO'));
      });
      d?.addEventListener('keydown', (ev) => {
        if ((ev.key === 'Enter' || ev.key === ' ') && ev.target.closest?.('.replay-button')) { ev.preventDefault(); ev.target.click(); }
      });
      if (autoplay) playSounds(d?.querySelectorAll('audio') || []);
    };
    el.frame.src = `${url}${isDark() ? '&night=1' : ''}`;
  }

  function render() {
    stopSay();
    const c = cards[i];
    revealed = false;
    el.card.hidden = false;
    const anki = !!c.anki;
    el.card.classList.toggle('has-anki', anki);
    el.frame.hidden = !anki;
    el.front.hidden = anki;
    el.answerBox.hidden = anki;
    if (anki) showFrame(c.anki.front); else { stopSounds(); el.frame.removeAttribute('src'); }
    el.front.textContent = c.front;
    el.front.className = 'glyph' + (c.front_kind === 'text' ? ' text-card' : c.front.length > 2 ? ' word' : '');
    el.front.lang = c.track === 'card' ? '' : 'ja';
    el.track.textContent = c.label + (c.requeued ? ' · again' : c.is_new ? ' · new' : '');
    el.answer.textContent = c.answer;
    const isKana = c.track === 'hiragana' || c.track === 'katakana';
    el.reading.textContent = (c.track === 'kanji' || c.track === 'dict') ? (c.reading || '') : (!isKana && showRomaji ? (c.reading || '') : '');
    el.extra.textContent = c.extra || '';
    showWordBack(c);
    el.hook.hidden = !c.hook;
    el.hookText.textContent = c.hook || '';
    const mine = [c.my_mnemonic, c.my_notes].filter(Boolean).join(' — ');
    el.mine.hidden = !mine;
    el.mineText.textContent = mine;
    if (c.track === 'kanji') { el.link.href = `/kanji/${encodeURIComponent(c.item)}`; el.link.hidden = false; }
    else if (c.track === 'dict') { el.link.href = `/dictionary?q=${encodeURIComponent(c.front)}`; el.link.hidden = false; }
    else el.link.hidden = true;
    for (const s of $$('[data-iv]', el.rate)) s.textContent = c.requeued ? '' : (c.previews?.[s.dataset.iv] || '');
    el.back.hidden = true; el.rate.hidden = true; el.showWrap.hidden = false;
    el.undo.hidden = !history.length;
    const real = cards.filter(x => !x.requeued).length;
    el.count.textContent = `${Math.min(done, real)}/${real}`;
    el.prog.style.width = `${(100 * i) / cards.length}%`;
    el.show.focus({ preventScroll: true });
  }

  function reveal() {
    if (revealed || finished) return;
    revealed = true;
    el.back.hidden = false; el.rate.hidden = false; el.showWrap.hidden = true;
    if (cards[i].anki) showFrame(cards[i].anki.back);
    else if (cards[i].say && autoplay) say(cards[i].say.text, cards[i].say.reading);
    el.rate.querySelector('.good').focus({ preventScroll: true });
  }

  function advance() {
    i++;
    if (i >= cards.length) finish(); else render();
  }

  async function rate(r) {
    if (!revealed || busy || finished) return;
    const c = cards[i];
    if (practice) {  // nothing is sent: practice never changes the schedule
      if (r === 1) { again++; cards.push({ ...c, requeued: true }); }
      else { done++; if (!c.requeued) firstTry++; }
      advance();
      return;
    }
    // A card rated "Again" comes back once at the end for practice. The server
    // only schedules it again in 10 minutes, so this extra pass isn't sent.
    if (c.requeued) { advance(); return; }
    busy = true;
    $$('[data-r]', el.rate).forEach(b => { b.disabled = true; });
    try {
      const res = await api('/api/review/submit', { card_id: c.id, rating: r });
      done++;
      history.push({ review_id: res.review_id, index: i, again: r === 1 });
      if (r === 1) { again++; cards.push({ ...c, requeued: true }); }
      if (res.mastered_now) { toast(`🌸 Mastered ${c.front}!`, 'gold', 3000); sparks(); }
      reward(res);
    } catch (e) {
      if (e.status !== 409) {
        toast(e.message, 'err');
        busy = false; $$('[data-r]', el.rate).forEach(b => { b.disabled = false; });
        return;
      }
    }
    $$('[data-r]', el.rate).forEach(b => { b.disabled = false; });
    busy = false;
    advance();
  }

  async function undo() {
    const last = history[history.length - 1];
    if (!last || busy) return;
    busy = true;
    try {
      const r = await api('/api/review/undo', { review_id: last.review_id });
      history.pop();
      done--;
      if (last.again) {  // drop the practice copy that "Again" queued at the end
        const k = cards.findLastIndex(x => x.requeued && x.id === cards[last.index].id);
        if (k > -1) cards.splice(k, 1);
        again--;
      }
      finished = false;
      el.done.hidden = true; $('.shortcuts', root).hidden = false;
      i = last.index;
      render();
      reward(r);
      toast('Undone ↶');
    } catch (e) { toast(e.message, 'err'); }
    busy = false;
  }

  function dropCurrent(msg) {
    const id = cards[i].id;
    for (let k = cards.length - 1; k > i; k--) if (cards[k].id === id) cards.splice(k, 1);
    cards.splice(i, 1);
    toast(msg);
    if (i >= cards.length) finish(); else render();
  }

  async function act(action) {
    const c = cards[i];
    if (!c || finished) return;
    if (action === 'edit') { openEditor(c); return; }
    try {
      await api(`/api/cards/${action}`, { ids: [c.id] });
      dropCurrent(action === 'bury' ? 'Buried until tomorrow ⏭' : 'Suspended ⏸ (unsuspend it in Browse)');
    } catch (e) { toast(e.message, 'err'); }
  }

  // ---- notes editor
  const dlg = $('#edit-note'), form = $('[data-note-form]');
  function openEditor(c) {
    $('[data-note-title]', dlg).textContent = c.front.slice(0, 30);
    form.meaning.value = c.my_meaning || '';
    form.mnemonic.value = c.my_mnemonic || '';
    form.notes.value = c.my_notes || '';
    dlg.showModal();
    form.meaning.focus();
  }
  form.addEventListener('submit', async (e) => {
    if (e.submitter?.value !== 'ok') return;
    e.preventDefault();
    const c = cards[i];
    try {
      const r = await api('/api/notes', { track: c.track, item: c.item, meaning: form.meaning.value, mnemonic: form.mnemonic.value, notes: form.notes.value });
      for (const x of cards) if (x.id === c.id) {
        x.my_meaning = r.meaning; x.my_mnemonic = r.mnemonic; x.my_notes = r.notes;
        if (r.meaning) x.answer = r.meaning;
      }
      dlg.close();
      const wasRevealed = revealed;
      render();
      if (wasRevealed) reveal();
      toast('Notes saved ✓');
    } catch (err) { toast(err.message, 'err'); }
  });

  function finish() {
    if (practice) return finishPractice();
    finished = true;
    el.card.hidden = true; el.rate.hidden = true; el.showWrap.hidden = true;
    $('.shortcuts', root).hidden = true;
    el.prog.style.width = '100%';
    el.count.textContent = `${done}/${done}`;
    el.done.hidden = false;
    $('[data-done-msg]', el.done).textContent = `${done} review${done === 1 ? '' : 's'} done${again ? `, ${again} to look at again soon` : ''}. Nice work.`;
    sparks();
  }

  function finishPractice() {
    finished = true;
    rounds++;
    el.card.hidden = true; el.rate.hidden = true; el.showWrap.hidden = true;
    $('.shortcuts', root).hidden = true;
    el.prog.style.width = '100%';
    const n = practiceSet.length;
    $('[data-done-msg]', el.done).textContent = `Round ${rounds}: ${firstTry} of ${n} right the first time${again ? `, ${again} repeat${again === 1 ? '' : 's'}` : ''}.`;
    el.done.hidden = false;
    $('[data-repeat]', el.done)?.focus();
    if (rounds === 1) api('/api/practice/done', { n }).then(reward).catch(() => {});
    if (firstTry === n) sparks();
  }

  function repeatPractice() {  // same words, new order
    cards.length = 0;
    const shuffled = practiceSet.map(c => ({ ...c, requeued: false })).sort(() => Math.random() - 0.5);
    cards.push(...shuffled);
    i = 0; done = 0; again = 0; firstTry = 0; finished = false;
    el.done.hidden = true; $('.shortcuts', root).hidden = false;
    render();
  }
  $('[data-repeat]', root)?.addEventListener('click', repeatPractice);

  el.show.addEventListener('click', reveal);
  el.card.addEventListener('click', (e) => { if (!e.target.closest('button,a,.menu')) reveal(); });
  el.rate.addEventListener('click', (e) => { const b = e.target.closest('[data-r]'); if (b) rate(+b.dataset.r); });
  el.undo.addEventListener('click', undo);
  root.addEventListener('click', (e) => {
    const a = e.target.closest('[data-act]');
    if (a) { a.closest('[data-menu]')?.classList.remove('open'); act(a.dataset.act); }
  });
  $('[data-more-quiz]', root)?.addEventListener('click', async (e) => {
    const b = e.currentTarget; b.classList.add('is-busy');
    try {
      const r = await api('/api/quiz/start', { kind: 'mixed', mode: burstActive() ? 'burst' : 'practice', pool: 'learned' });
      location.href = r.url;
    } catch (err) { b.classList.remove('is-busy'); toast(err.message, 'err', 4000); }
  });
  // Undo stays available on the "done" screen too.
  el.done.querySelector('.row').insertAdjacentHTML('afterbegin', '<button class="btn lg" type="button" data-undo-done>↶ Undo</button>');
  $('[data-undo-done]', root).addEventListener('click', undo);
  document.addEventListener('keydown', (e) => {
    if (e.target.closest('input,textarea,select') || e.metaKey || e.ctrlKey || e.altKey || dlg.open) return;
    const k = e.key.toLowerCase();
    if (practice && finished && e.key === 'Enter') { e.preventDefault(); repeatPractice(); return; }
    if (practice && /^[1-4]$/.test(e.key)) { e.preventDefault(); rate(e.key === '1' ? 1 : 3); return; }
    if (practice && (k === 'z' || e.key === '-' || e.key === '@')) return;
    if (k === 'z') { e.preventDefault(); undo(); return; }
    if (finished) return;
    if ((e.key === ' ' || e.key === 'Enter') && !revealed) { e.preventDefault(); reveal(); }
    else if (/^[1-4]$/.test(e.key)) { e.preventDefault(); rate(+e.key); }
    else if (k === 'e') { e.preventDefault(); act('edit'); }
    else if (k === 'r' && cards[i]?.anki) { e.preventDefault(); replay(); }
    else if (k === 'r' && cards[i]?.say) { e.preventDefault(); say(cards[i].say.text, cards[i].say.reading); }
    else if (e.key === '-') { e.preventDefault(); act('bury'); }
    else if (e.key === '@') { e.preventDefault(); act('suspend'); }
  });
  render();
}

// Words: furigana + which reading each kanji uses + an example. Kanji cards: real words that use the kanji.
function showWordBack(c) {
  const box = $('[data-wordback]'), rows = $('[data-wb-rows]'), hint = $('[data-wb-hint]'), sent = $('[data-wb-sentence]');
  const reading = $('[data-reading]');
  rows.replaceChildren(); sent.replaceChildren(); hint.textContent = '';
  let any = false;
  if (c.parts) { reading.replaceChildren(furigana(c.parts)); any = true; }
  if (c.say) reading.append(sayButton(c.say.text, c.say.reading));
  if (c.kanji?.length) { rows.append(kanjiRows(c.kanji)); any = true; }
  if (c.kana_rows?.length) { const k = h('div', 'center'); k.append(kanaRows(c.kana_rows)); rows.append(k, kanaNotes(c.kana_rows)); any = true; }
  if (c.hint) { hint.textContent = c.hint; any = true; }
  if (c.words?.length) {
    const ul = h('ul', 'kw-list');
    for (const w of c.words) { const li = h('li'); li.append(h('span', 'jp', w.word), ' ', h('span', 'jp muted', w.reading), ' — ', w.meaning); ul.append(li); }
    rows.append(h('p', 'tiny muted', 'In words:'), ul); any = true;
  }
  if (c.sentence_jp) { sent.append(h('p', 'sentence-jp', c.sentence_jp), h('p', 'small muted', c.sentence_en || '')); any = true; }
  box.hidden = !any;
}

// Practice controls: slider shows its number; changing the deck or the kind of words reloads straight away.
const pf = document.querySelector('[data-practice-form]');
if (pf) {
  const out = pf.querySelector('[data-pr-n-out]');
  pf.n.addEventListener('input', () => { out.textContent = pf.n.value; });
  pf.n.addEventListener('change', () => pf.requestSubmit());
  for (const s of pf.querySelectorAll('select')) s.addEventListener('change', () => pf.requestSubmit());
}
