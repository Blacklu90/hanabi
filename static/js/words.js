import { $, api, reward, toast } from './app.js';
import { wireAddWord } from './words-ui.js';

wireAddWord();
const form = $('[data-add-words]');
form?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const btn = e.submitter, st = $('[data-aw-status]', form);
  btn.disabled = true;
  try {
    const r = await api(form.dataset.url || '/api/words/add', { count: Number(btn.value), deck: Number(form.deck.value) || 0 });
    st.textContent = `Added ${r.added} words to “${r.deck}”. Opening your deck…`;
    reward(r);
    setTimeout(() => { location.href = `/review?deck=${r.deck_id}`; }, 900);
  } catch (err) { btn.disabled = false; st.textContent = ''; toast(err.message, 'err'); }
});
