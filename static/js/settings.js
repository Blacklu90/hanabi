import { $, $$ } from './app.js';

const form = $('[data-settings]');
// Live value labels next to sliders
for (const r of $$('input[type=range]', form)) {
  const out = $(`[data-out="${r.name}"]`, form);
  r.addEventListener('input', () => { out.textContent = r.value; });
}
// Theme preview is instant; saving makes it stick.
for (const r of $$('[data-theme-pick]', form)) r.addEventListener('change', () => { document.documentElement.dataset.theme = r.value; });
for (const r of $$('[data-palette-pick]', form)) r.addEventListener('change', () => { document.documentElement.dataset.palette = r.value; });
$('[name=calm_mode]', form).addEventListener('change', (e) => { document.documentElement.dataset.calm = e.target.checked ? '1' : '0'; });
$('[data-tz-detect]', form).addEventListener('click', () => {
  try { $('[data-tz-field]', form).value = Intl.DateTimeFormat().resolvedOptions().timeZone; } catch { /* ignore */ }
});

// Daily reminder (Android app only; saved on the phone straight away)
import('./app.js').then(({ android }) => {
  const box = document.querySelector('[data-android-only]');
  if (!android || !box || !android.getReminder) return;
  box.hidden = false;
  const on = box.querySelector('[data-remind-on]'), time = box.querySelector('[data-remind-time]'), note = box.querySelector('[data-remind-note]');
  const load = () => {
    const r = JSON.parse(android.getReminder());
    on.checked = r.enabled;
    time.value = `${String(r.hour).padStart(2, '0')}:${String(r.minute).padStart(2, '0')}`;
  };
  const save = () => {
    const [h, m] = (time.value || '19:00').split(':').map(Number);
    android.setReminder(on.checked, h, m);
    note.textContent = on.checked ? `Reminder set for ${time.value} every day.` : 'Reminder is off.';
  };
  load();
  on.addEventListener('change', save);
  time.addEventListener('change', () => { if (on.checked) save(); });
  window.addEventListener('reminderchange', load);
});

// Voice: show whether the built-in voice is installed; install it with one click (Linux/macOS).
import('./app.js').then(({ api, get, android }) => {
  const card = document.querySelector('[data-voice-card]');
  if (!card) return;
  const st = card.querySelector('[data-voice-state]'), btn = card.querySelector('[data-voice-install]');
  let timer = null;
  const show = (r) => {
    if (r.installed) { st.textContent = 'The built-in voice is installed. ✓'; btn.hidden = true; return; }
    if (r.state === 'working') { st.textContent = r.message || 'Installing…'; btn.hidden = true; return; }
    if (android) { st.textContent = 'On your phone, Shuinkan uses the phone\'s own Japanese voice.'; btn.hidden = true; return; }
    st.textContent = r.state === 'error' ? r.message : (r.can_install ? 'The built-in voice isn\'t installed yet.' : 'The built-in voice isn\'t available on this device.');
    btn.hidden = !r.can_install;
  };
  const poll = () => { clearInterval(timer); timer = setInterval(async () => { const r = await get('/api/voice'); show(r); if (r.state !== 'working') clearInterval(timer); }, 1500); };
  get('/api/voice').then((r) => { show(r); if (r.state === 'working') poll(); }).catch(() => { st.textContent = ''; });
  btn.addEventListener('click', async () => { btn.disabled = true; try { show(await api('/api/voice/install', {})); poll(); } catch (e) { st.textContent = e.message; } btn.disabled = false; });
});
