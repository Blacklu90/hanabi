// Shuinkan core: fetch helper, toasts, celebrations, menus, focus bursts.
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
export { $, $$ };

const csrf = () => document.querySelector('meta[name="csrf"]')?.content || '';
export const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches || document.documentElement.dataset.calm === '1';

export async function api(url, body, method = 'POST') {
  const opts = { method, headers: { 'X-CSRF-Token': csrf(), Accept: 'application/json' }, credentials: 'same-origin' };
  if (body !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
  let res;
  try { res = await fetch(url, opts); } catch { toast('You seem to be offline. Try again in a moment.', 'err'); throw new Error('offline'); }
  let data = {};
  try { data = await res.json(); } catch { /* non-JSON */ }
  if (!res.ok || data.ok === false) {
    if (res.status === 401) { location.href = '/login?next=' + encodeURIComponent(location.pathname); }
    const e = new Error(data.error || `Request failed (${res.status})`); e.status = res.status; e.data = data; throw e;
  }
  return data;
}
export const get = (url) => api(url, undefined, 'GET');

// ------------------------------------------------------------ toasts
export function toast(msg, kind = '', ms = 2600) {
  const box = $('.toasts'); if (!box) return;
  const t = document.createElement('div');
  t.className = 'toast ' + kind; t.textContent = msg;
  box.append(t);
  setTimeout(() => t.remove(), ms);
}

// ------------------------------------------------------- celebrations
const celebrateOn = () => document.body.dataset.celebrate !== '0' && !reduced();
export function sparks(x = innerWidth / 2, y = innerHeight / 3, n = 18) {
  if (!celebrateOn()) return;
  let layer = $('.spark-layer');
  if (!layer) { layer = document.createElement('div'); layer.className = 'spark-layer'; document.body.append(layer); }
  const colors = ['var(--accent)', 'var(--gold)', 'var(--indigo)', 'var(--good)'];
  for (let i = 0; i < n; i++) {
    const s = document.createElement('i'); s.className = 'spark';
    const a = (Math.PI * 2 * i) / n + Math.random() * .4, d = 60 + Math.random() * 90;
    s.style.cssText = `left:${x}px;top:${y}px;background:${colors[i % 4]};--dx:${Math.cos(a) * d}px;--dy:${Math.sin(a) * d}px`;
    layer.append(s); setTimeout(() => s.remove(), 950);
  }
}

/** Show XP / level / achievements from any write API response. */
export function reward(r, el) {
  if (!r) return;
  if (r.xp > 0 && celebrateOn()) toast(`+${r.xp} XP`, 'gold', 1400);
  for (const a of r.achievements || []) {
    toast(`${a.icon}  Achievement: ${a.title}${a.xp ? ` · +${a.xp} XP` : ''}`, 'gold', 4200);
    sparks();
  }
  if (r.level) {
    const chip = $('.xp-chip');
    if (chip) chip.textContent = `Lv ${r.level.level} · ${r.level.xp} XP`;
  }
  if (r.goal && r.today_xp >= r.goal && r.today_xp - (r.xp || 0) < r.goal) {
    toast('🎯 Daily goal reached! Anything more is a bonus.', 'gold', 3800); sparks();
  }
  if (el && r.xp > 0) { const b = el.getBoundingClientRect(); sparks(b.left + b.width / 2, b.top + b.height / 2, 10); }
}

// ------------------------------------------------------ time labels
const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });
export function ago(ts) {
  const s = Math.round(ts - Date.now() / 1000), a = Math.abs(s);
  if (a < 60) return rtf.format(Math.round(s), 'second');
  if (a < 3600) return rtf.format(Math.round(s / 60), 'minute');
  if (a < 86400) return rtf.format(Math.round(s / 3600), 'hour');
  return rtf.format(Math.round(s / 86400), 'day');
}
function stampTimes(root = document) {
  for (const el of $$('[data-ago]', root)) el.textContent = ago(+el.dataset.ago);
  for (const el of $$('[data-at]', root)) el.textContent = +el.dataset.at <= Date.now() / 1000 ? 'now' : ago(+el.dataset.at);
  for (const el of $$('[data-date]', root)) el.textContent = new Date(+el.dataset.date * 1000).toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });
}

// ---------------------------------------------------------- burst
const BURST_KEY = 'shuinkan-burst';
function burstState() { try { return JSON.parse(sessionStorage.getItem(BURST_KEY) || 'null'); } catch { return null; } }
function setBurst(v) { try { v ? sessionStorage.setItem(BURST_KEY, JSON.stringify(v)) : sessionStorage.removeItem(BURST_KEY); } catch { /* storage off */ } }
export async function startBurst() {
  const r = await api('/api/burst/start', {});
  setBurst({ id: r.id, end: Date.now() + r.minutes * 60000, minutes: r.minutes });
  location.href = '/review?burst=1';
}
async function finishBurst(b) {
  setBurst(null);
  try {
    const r = await api('/api/burst/complete', { id: b.id });
    if (r.counted) { toast(`🎆 Burst done: ${r.items} items. Take a short break, you earned it.`, 'gold', 6000); sparks(); reward(r); }
    else toast(r.message || 'Burst ended.', '', 4000);
  } catch (e) { toast(e.message, 'err'); }
}
function tickBurst() {
  const b = burstState(); if (!b) return;
  const el = $('[data-burst-timer]') || (() => {
    const t = document.createElement('a'); t.className = 'timer'; t.href = '/review'; t.dataset.burstTimer = '';
    t.style.cssText = 'position:fixed;right:14px;bottom:84px;z-index:40;text-decoration:none;box-shadow:var(--shadow-2)';
    document.body.append(t); return t;
  })();
  el.hidden = false;
  const left = Math.max(0, b.end - Date.now());
  const m = Math.floor(left / 60000), s = Math.floor(left / 1000) % 60;
  el.textContent = `⏱ ${m}:${String(s).padStart(2, '0')}`;
  el.classList.toggle('low', left < 30000);
  el.title = 'Focus burst time left';
  if (left <= 0) { el.remove(); finishBurst(b); return; }
  setTimeout(tickBurst, 1000 - (Date.now() % 1000) + 5);
}
export function burstActive() { const b = burstState(); return !!(b && b.end > Date.now()); }

// ------------------------------------------------------- wiring
document.addEventListener('click', (e) => {
  const menu = e.target.closest('[data-menu]');
  const btn = e.target.closest('.menu-btn');
  if (btn) { const m = btn.closest('[data-menu]'); const open = !m.classList.contains('open'); m.classList.toggle('open', open); btn.setAttribute('aria-expanded', open); return; }
  if (e.target.closest('[data-open-menu]')) {
    e.preventDefault();
    const m = $('[data-menu]'); m.classList.add('open'); m.querySelector('.menu-btn').setAttribute('aria-expanded', 'true');
    m.querySelector('.menu-pop a')?.focus(); return;
  }
  if (!menu) $$('[data-menu].open').forEach(m => { m.classList.remove('open'); m.querySelector('.menu-btn').setAttribute('aria-expanded', 'false'); });
  const burst = e.target.closest('[data-burst]');
  if (burst) { burst.classList.add('is-busy'); startBurst().catch(err => { burst.classList.remove('is-busy'); toast(err.message, 'err'); }); }
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    const open = $('[data-menu].open');
    if (open) { open.classList.remove('open'); open.querySelector('.menu-btn').focus(); return; }
    if (document.body.classList.contains('focus') && !e.target.closest('input,textarea,select')) {
      const exit = $('.focus-bar .exit'); if (exit) location.href = exit.href;
    }
  }
});
for (const el of $$('[data-tz]')) { try { el.value = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'; } catch { /* keep UTC */ } }
// Mobile tab bar sits above the toasts
stampTimes();
tickBurst();
// Prevent double submit on plain forms
document.addEventListener('submit', (e) => {
  const b = e.target.querySelector('button[type=submit]');
  if (b) setTimeout(() => b.classList.add('is-busy'), 0);
});
window.addEventListener('pageshow', (e) => { if (e.persisted) $$('.is-busy').forEach(b => b.classList.remove('is-busy')); });

// ---------------------------------------------------------------- Android app
// Inside the Android app, colour the status and navigation bars like the page (theme, palette, dark mode).
export const android = window.ShuinkanAndroid || null;
function syncBars() {
  if (!android) return;
  const bg = getComputedStyle(document.body).backgroundColor.match(/\d+/g);
  if (!bg) return;
  const [r, g, b] = bg.map(Number);
  const hex = '#' + [r, g, b].map((x) => x.toString(16).padStart(2, '0')).join('');
  const dark = (0.299 * r + 0.587 * g + 0.114 * b) < 128;
  try { android.setBars(hex, dark); } catch { /* older app */ }
}
if (android) {
  document.documentElement.classList.add('in-android');
  syncBars();
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', syncBars);
  new MutationObserver(syncBars).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'data-palette'] });
}

// ▶ buttons (data-say) work on every page; the voice code loads the first time one is used.
document.addEventListener('click', (e) => {
  if (!e.target.closest('[data-say]') || window.__sayLoaded) return;
  window.__sayLoaded = true;
  e.preventDefault();
  import('./speak.js').then(() => e.target.closest('[data-say]').click());
}, true);
