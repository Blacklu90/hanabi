// Hear a word: your Anki decks' recording, else the built-in voice, else the device's Japanese voice.
import { get, toast } from './app.js';

const answers = new Map();
let current = null;

function deviceSpeak(text) {
  const a = window.ShuinkanAndroid;
  if (a && a.speak) {
    try { if (a.speak(text)) return true; } catch { /* older app */ }
    toast('Your phone has no Japanese voice yet. Add one in the phone\'s Settings → Language → Text-to-speech.', 'err', 6000);
    return false;
  }
  if ('speechSynthesis' in window) {
    const v = speechSynthesis.getVoices().find((x) => x.lang && x.lang.toLowerCase().startsWith('ja'));
    if (v) {
      speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(text);
      u.voice = v; u.lang = 'ja-JP'; u.rate = 0.9;
      speechSynthesis.speak(u);
      return true;
    }
  }
  return false;
}

export function stop() {
  if (current) { current.pause(); current = null; }
  try { window.speechSynthesis?.cancel(); } catch { /* none */ }
}

export async function say(text, reading = '') {
  if (!text) return false;
  const key = `${text}|${reading}`;
  let r = answers.get(key);
  if (!r) {
    try { r = await get(`/api/say?text=${encodeURIComponent(text)}&reading=${encodeURIComponent(reading)}`); }
    catch (e) { toast(e.message, 'err'); return false; }
    answers.set(key, r);
  }
  stop();
  if (r.url) {
    current = new Audio(r.url);
    try { await current.play(); return true; } catch { /* fall through to the device voice */ }
  }
  if (deviceSpeak(r.text || reading || text)) return true;
  toast(r.can_install ? 'No Japanese voice yet. Install the built-in voice in Settings → Voice (one time).'
    : 'No Japanese voice on this device.', 'err', 6000);
  return false;
}

// Any element with data-say="word" (and optionally data-reading="かな") becomes a ▶ button.
document.addEventListener('click', (e) => {
  const b = e.target.closest('[data-say]');
  if (!b) return;
  e.preventDefault();
  b.classList.add('playing');
  say(b.dataset.say, b.dataset.reading || '').finally(() => setTimeout(() => b.classList.remove('playing'), 600));
});

export function sayButton(text, reading = '', label = '') {
  const b = document.createElement('button');
  b.type = 'button'; b.className = 'say'; b.dataset.say = text;
  if (reading) b.dataset.reading = reading;
  b.setAttribute('aria-label', `Hear ${label || text}`);
  b.title = 'Hear it';
  b.textContent = '▶';
  return b;
}
