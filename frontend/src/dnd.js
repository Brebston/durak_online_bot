// Чиста логіка drag-and-drop: яку дію виконати, коли карту кинули на стіл.
// Сервер однаково перевірить хід — тут лише вибір наміру гравця.

/**
 * @param {Array} actions   дозволені дії з сервера
 * @param {string} card     карта, яку кинули
 * @param {object} drop     { overPair: number|null, nearest: number[]  (індекси пар від найближчої), onTable: boolean }
 * @returns {object|null}   дія для відправки або null (карта повертається в руку)
 */
export function resolveDrop(actions, card, drop) {
  const opts = actions.filter((a) => a.card === card && a.type !== 'catch')
  if (!opts.length || !drop.onTable) return null
  // чесні варіанти — першими (у режимі «Шулер» є ще й мухлювання)
  const defends = opts.filter((a) => a.type === 'defend').sort((a, b) => Boolean(a.cheat) - Boolean(b.cheat))
  const transfer = opts.find((a) => a.type === 'transfer')
  const attack = opts.find((a) => a.type === 'attack' && !a.cheat) || opts.find((a) => a.type === 'attack')

  // кинули прямо на карту суперника — відбиваємо саме її
  if (drop.overPair !== null && drop.overPair !== undefined) {
    const d = defends.find((a) => a.target === drop.overPair)
    if (d) return d
  }
  if (attack) return attack
  // кинули на вільне місце: переводимо, якщо можна
  if (transfer && (drop.overPair === null || drop.overPair === undefined)) return transfer
  // інакше — відбиваємо найближчу карту, яку ця карта може побити
  for (const honest of [true, false]) {
    for (const i of drop.nearest || []) {
      const d = defends.find((a) => a.target === i && !a.cheat === honest)
      if (d) return d
    }
  }
  return defends[0] || transfer || null
}

/** Індекси пар на столі, відсортовані за відстанню від точки (x, y). */
export function nearestPairs(rects, x, y) {
  return rects
    .map((r, i) => ({ i, d: Math.hypot(r.left + r.width / 2 - x, r.top + r.height / 2 - y) }))
    .sort((a, b) => a.d - b.d)
    .map((o) => o.i)
}

/** Чи точка всередині прямокутника (з запасом pad). */
export function inside(r, x, y, pad = 0) {
  return x >= r.left - pad && x <= r.right + pad && y >= r.top - pad && y <= r.bottom + pad
}
