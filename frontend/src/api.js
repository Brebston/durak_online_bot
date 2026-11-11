import { t } from './i18n.js'
// Клієнт API та WebSocket. Клієнт НЕ рахує баланс і не вирішує, чи хід дозволений:
// сервер надсилає список дозволених дій, а кожен хід перевіряє сам.

export const tg = window.Telegram?.WebApp

function authHeader() {
  if (tg?.initData) return `tma ${tg.initData}`
  // локальна розробка без Telegram: ?dev=<id>&name=<ім'я> (працює лише з DEV_MODE=1 на сервері)
  const q = new URLSearchParams(location.search)
  const id = q.get('dev') || localStorage.getItem('dev_id') || '1'
  try { localStorage.setItem('dev_id', id) } catch { /* ignore */ }
  return `dev ${id}:${encodeURIComponent(q.get('name') || t('Гравець ') + id)}`;
}

export async function api(path, body) {
  const r = await fetch(path, {
    method: body ? 'POST' : 'GET',
    headers: { Authorization: authHeader(), ...(body ? { 'Content-Type': 'application/json' } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  })
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(typeof data.detail === 'string' ? t(data.detail) : t('Помилка {0}', r.status))
  return data
}

export class GameSocket {
  constructor(onMessage, onStatus) {
    this.onMessage = onMessage
    this.onStatus = onStatus
    this.queue = []
    this.closed = false
    this.retry = 0
    this.connect()
  }

  connect() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    this.ws = new WebSocket(`${proto}://${location.host}/ws`)
    this.ws.onopen = () => {
      this.retry = 0
      this.ws.send(JSON.stringify({ auth: authHeader() }))
      this.onStatus?.('online')
      this.queue.splice(0).forEach((m) => this.ws.send(m))
    }
    this.ws.onmessage = (e) => {
      const m = JSON.parse(e.data)
      if (m.fatal) this.closed = true // помилка авторизації — не перепідключаємось безкінечно
      this.onMessage(m)
    }
    this.ws.onclose = () => {
      this.onStatus?.('offline')
      if (this.closed) return
      const delay = Math.min(10000, 500 * 2 ** this.retry++)
      setTimeout(() => this.connect(), delay)
    }
  }

  send(msg) {
    const s = JSON.stringify(msg)
    if (this.ws?.readyState === 1) this.ws.send(s)
    else this.queue.push(s)
  }

  close() {
    this.closed = true
    this.ws?.close()
  }
}

export const SUIT = { S: '♠', C: '♣', D: '♦', H: '♥' }
export const RANK = { 11: t('В'), 12: t('Д'), 13: t('К'), 14: t('Т') }
export const rankOf = (c) => parseInt(c.slice(0, -1), 10)
export const suitOf = (c) => c.slice(-1)
export const label = (c) => `${RANK[rankOf(c)] || rankOf(c)}${SUIT[suitOf(c)]}`

export function haptic(type = 'light') {
  try { tg?.HapticFeedback?.impactOccurred(type) } catch { /* ignore */ }
}

let audioCtx
export function beep(freq = 660, ms = 90) {
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)()
    const o = audioCtx.createOscillator()
    const g = audioCtx.createGain()
    o.frequency.value = freq
    g.gain.value = 0.05
    o.connect(g).connect(audioCtx.destination)
    o.start()
    o.stop(audioCtx.currentTime + ms / 1000)
  } catch { /* ignore */ }
}
