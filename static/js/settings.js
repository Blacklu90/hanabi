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
