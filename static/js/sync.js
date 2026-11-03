// Wi-Fi sync page: host (show a code, wait) or join (type address + code).
import { $, api, get, toast } from './app.js';

const host = $('[data-host]'), join = $('[data-join]');
const q = (s, r = host) => $(s, r);
let timer = null;

function summary(st) {
  const p = [];
  p.push(`${st.cards_new} new card${st.cards_new === 1 ? '' : 's'}`, `${st.cards_updated} updated`, `${st.reviews} reviews`);
  if (st.lessons) p.push(`${st.lessons} lessons`);
  if (st.custom) p.push(`${st.custom} imported cards`);
  if (st.media) p.push(`${st.media} media files`);
  if (st.notes) p.push(`${st.notes} notes`);
  return p.join(', ');
}

function showResult(box, ok, text) {
  box.hidden = false;
  box.className = 'alert ' + (ok ? 'ok' : 'err');
  box.textContent = text;
}

function render(st) {
  const on = st.state === 'waiting' || st.state === 'syncing';
  q('[data-host-off]').hidden = on;
  q('[data-host-on]').hidden = !on;
  if (on) {
    q('[data-code]').textContent = st.code;
    q('[data-addr]').textContent = st.addresses.map((a) => `${a}:${st.port}`).join('  or  ');
    const m = Math.floor(st.expires_in / 60), s = String(st.expires_in % 60).padStart(2, '0');
    q('[data-left]').textContent = st.state === 'syncing' ? 'Syncing…' : `(code works for ${m}:${s})`;
  }
  if (st.state === 'done' && st.result) {
    showResult(q('[data-host-result]'), true, `Synced with ${st.peer}. Got ${summary(st.result)}.`);
    stopPolling();
  } else if (st.state === 'closed' && st.error && st.error !== 'Stopped.') {
    showResult(q('[data-host-result]'), false, st.error);
    stopPolling();
  }
}

function stopPolling() { clearInterval(timer); timer = null; }
function poll() {
  stopPolling();
  timer = setInterval(async () => {
    try { const st = await get('/api/sync/host'); render(st); if (!['waiting', 'syncing'].includes(st.state)) stopPolling(); }
    catch { /* keep trying */ }
  }, 1500);
}

q('[data-host-start]').addEventListener('click', async (e) => {
  e.target.disabled = true;
  q('[data-host-result]').hidden = true;
  try { render(await api('/api/sync/host', {})); poll(); }
  catch (err) { toast(err.message, 'err'); }
  e.target.disabled = false;
});
q('[data-host-stop]').addEventListener('click', async () => {
  stopPolling();
  await api('/api/sync/host/stop', {}).catch(() => {});
  render({ state: 'off' });
});

join.addEventListener('submit', async (e) => {
  e.preventDefault();
  const btn = $('button[type=submit]', join), box = $('[data-join-result]', join);
  btn.disabled = true; btn.textContent = 'Syncing…'; box.hidden = true;
  try {
    const r = await api('/api/sync/join', { address: join.address.value, code: join.code.value });
    showResult(box, true, `Synced with ${r.peer}. Got ${summary(r.received)}.`);
    try { localStorage.setItem('sync-addr', join.address.value); } catch { /* private mode */ }
  } catch (err) { showResult(box, false, err.message); }
  btn.disabled = false; btn.textContent = 'Sync now';
});
try { const a = localStorage.getItem('sync-addr'); if (a) join.address.value = a; } catch { /* private mode */ }

get('/api/sync/host').then((st) => { if (st.state === 'waiting' || st.state === 'syncing') { render(st); poll(); } }).catch(() => {});
