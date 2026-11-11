// Мʼякі звуки, синтезовані через Web Audio (без аудіофайлів).
// sfx.play('card') — шурхіт кинутої карти, 'take' — збирання карт, 'beaten' — «бито»,
// 'turn' — тихий дзвіночок «ваш хід», 'win'/'lose' — фінал, 'emoji' — «поп», 'coin' — покупка.

let ctx
let master
let enabled = true

function ac() {
  if (!ctx) {
    const AC = window.AudioContext || window.webkitAudioContext
    if (!AC) return null
    ctx = new AC()
    master = ctx.createGain()
    master.gain.value = 0.55
    // легка компресія, щоб звуки не «різали» вухо
    const comp = ctx.createDynamicsCompressor()
    comp.threshold.value = -18
    comp.ratio.value = 3
    master.connect(comp).connect(ctx.destination)
  }
  if (ctx.state === 'suspended') ctx.resume()
  return ctx
}

let noiseBuf
function noise() {
  if (!noiseBuf) {
    noiseBuf = ctx.createBuffer(1, ctx.sampleRate * 0.5, ctx.sampleRate)
    const d = noiseBuf.getChannelData(0)
    for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1
  }
  const src = ctx.createBufferSource()
  src.buffer = noiseBuf
  return src
}

// шурхіт паперу: короткий шум через смуговий фільтр
function swish(t, { dur = 0.09, freq = 2600, q = 0.9, vol = 0.5 } = {}) {
  const src = noise()
  const bp = ctx.createBiquadFilter()
  bp.type = 'bandpass'
  bp.frequency.setValueAtTime(freq * 1.4, t)
  bp.frequency.exponentialRampToValueAtTime(freq * 0.6, t + dur)
  bp.Q.value = q
  const g = ctx.createGain()
  g.gain.setValueAtTime(0.0001, t)
  g.gain.exponentialRampToValueAtTime(vol, t + 0.008)
  g.gain.exponentialRampToValueAtTime(0.0001, t + dur)
  src.connect(bp).connect(g).connect(master)
  src.start(t, Math.random() * 0.3, dur + 0.02)
}

// мʼякий стук карти об сукно
function thud(t, vol = 0.35) {
  const o = ctx.createOscillator()
  const g = ctx.createGain()
  o.type = 'sine'
  o.frequency.setValueAtTime(190, t)
  o.frequency.exponentialRampToValueAtTime(70, t + 0.08)
  g.gain.setValueAtTime(0.0001, t)
  g.gain.exponentialRampToValueAtTime(vol, t + 0.005)
  g.gain.exponentialRampToValueAtTime(0.0001, t + 0.1)
  o.connect(g).connect(master)
  o.start(t)
  o.stop(t + 0.12)
}

// дзвіночок: синус + тихий обертон, довге загасання
function bell(t, freq, { dur = 0.6, vol = 0.18 } = {}) {
  for (const [mult, v] of [[1, 1], [2.01, 0.25], [3.02, 0.08]]) {
    const o = ctx.createOscillator()
    const g = ctx.createGain()
    o.type = 'sine'
    o.frequency.value = freq * mult
    g.gain.setValueAtTime(0.0001, t)
    g.gain.exponentialRampToValueAtTime(vol * v, t + 0.01)
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur)
    o.connect(g).connect(master)
    o.start(t)
    o.stop(t + dur + 0.05)
  }
}

const SOUNDS = {
  card(t) { swish(t, { dur: 0.08 }); thud(t + 0.06, 0.25) },
  take(t) { for (let i = 0; i < 4; i++) swish(t + i * 0.045, { dur: 0.07, freq: 2000 + i * 200, vol: 0.3 }) },
  beaten(t) { swish(t, { dur: 0.22, freq: 1500, q: 0.6, vol: 0.35 }) },
  deal(t) { for (let i = 0; i < 6; i++) swish(t + i * 0.06, { dur: 0.05, freq: 3000, vol: 0.25 }) },
  turn(t) { bell(t, 880, { dur: 0.5, vol: 0.12 }); bell(t + 0.11, 1318.5, { dur: 0.7, vol: 0.1 }) },
  win(t) { [523.25, 659.25, 783.99, 1046.5].forEach((f, i) => bell(t + i * 0.11, f, { dur: 0.9, vol: 0.14 })) },
  lose(t) { [392, 329.63, 261.63].forEach((f, i) => bell(t + i * 0.16, f, { dur: 0.8, vol: 0.12 })) },
  emoji(t) {
    const o = ctx.createOscillator(); const g = ctx.createGain()
    o.type = 'sine'
    o.frequency.setValueAtTime(500, t); o.frequency.exponentialRampToValueAtTime(1100, t + 0.07)
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.15, t + 0.01); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.12)
    o.connect(g).connect(master); o.start(t); o.stop(t + 0.14)
  },
  coin(t) { bell(t, 1567.98, { dur: 0.35, vol: 0.12 }); bell(t + 0.08, 2093, { dur: 0.5, vol: 0.1 }) },
  click(t) { swish(t, { dur: 0.03, freq: 4000, vol: 0.15 }) },
}

export const sfx = {
  setEnabled(v) { enabled = !!v },
  play(name) {
    if (!enabled) return
    try {
      const c = ac()
      if (c && SOUNDS[name]) SOUNDS[name](c.currentTime + 0.01)
    } catch { /* ignore */ }
  },
}

// iOS/Telegram дозволяють звук лише після першого дотику
if (typeof window !== 'undefined') {
  const unlock = () => { try { ac() } catch { /* ignore */ } window.removeEventListener('pointerdown', unlock) }
  window.addEventListener('pointerdown', unlock)
}
