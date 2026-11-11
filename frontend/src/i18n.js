// Переклади. Ключ — український текст; для інших мов — словники в ./locales.
// Мова: вибір у Кабінеті → мова Telegram → англійська для решти.
import en from './locales/en.json'
import pl from './locales/pl.json'
import ru from './locales/ru.json'

const DICTS = { en, pl, ru }
export const LANGS = [['uk', 'Українська'], ['en', 'English'], ['pl', 'Polski'], ['ru', 'Русский']]

function detect() {
  try {
    const saved = localStorage.getItem('lang')
    if (saved === 'uk' || DICTS[saved]) return saved
  } catch { /* ignore */ }
  const code = (window.Telegram?.WebApp?.initDataUnsafe?.user?.language_code || navigator.language || 'uk')
    .slice(0, 2).toLowerCase()
  if (code === 'uk' || DICTS[code]) return code
  return 'en'
}

export const lang = detect()
if (typeof document !== 'undefined') document.documentElement.lang = lang

export function t(key, ...args) {
  if (key == null) return ''
  const d = DICTS[lang]
  const s = (d && d[key]) || key
  return args.length ? s.replace(/\{(\d+)\}/g, (_, i) => (args[i] ?? '')) : s
}

/** Змінити мову: зберігаємо й перезавантажуємо Mini App, щоб усі тексти оновились. */
export function setLang(l) {
  try { localStorage.setItem('lang', l) } catch { /* ignore */ }
  location.reload()
}
