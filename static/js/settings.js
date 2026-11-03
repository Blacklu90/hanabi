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
