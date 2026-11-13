import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { api, haptic, rankOf, suitOf, SUIT, tg } from '../api.js'
import { Chip } from '../Fx.jsx'
import { sfx } from '../sounds.js'
import { inside, nearestPairs, resolveDrop } from '../dnd.js'
import { Avatar, Victory } from '../Fx.jsx'
import { t } from '../i18n.js'
import PlayerCard from './PlayerCard.jsx'

const RANKS = { 11: t('В'), 12: t('Д'), 13: t('К'), 14: t('Т') }

export function Card({ c, small, className = '', ...rest }) {
  const red = suitOf(c) === 'H' || suitOf(c) === 'D'
  return (
    <div className={`pcard ${red ? 'red' : ''} ${small ? 'small' : ''} ${className}`} data-card={c} {...rest}>
      <span className="tl">{RANKS[rankOf(c)] || rankOf(c)}<br />{SUIT[suitOf(c)]}</span>
      <span className="mid">{SUIT[suitOf(c)]}</span>
    </div>
  )
}

function Backs({ n, back }) {
  const shown = Math.min(n, 8)
  return (
    <div className="backs">
      {Array.from({ length: shown }).map((_, i) => <div key={i} className={`back cb-${back || 'back_classic'}`} style={{ left: i * 7 }} />)}
    </div>
  )
}

function useNow(active) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    if (!active) return
    const timer = setInterval(() => setNow(Date.now()), 250)
    return () => clearInterval(timer)
  }, [active])
  return now
}

export default function Room({ data, me, send, onExit, onAgain, toast }) {
  const { room } = data
  const [offset] = useState(() => room.now * 1000 - Date.now())
  const now = useNow(room.status === 'playing' || room.status === 'waiting')
  const serverNow = now + offset
  if (room.status === 'waiting') return <Waiting room={room} send={send} onExit={onExit} me={me} serverNow={serverNow} toast={toast} />
  const left = Math.min(room.rules.turn_seconds * 1000, Math.max(0, room.deadline * 1000 - serverNow))
  return <Table data={data} me={me} send={send} left={left} onExit={onExit} onAgain={onAgain} serverNow={serverNow} toast={toast} />
}

// ======================= Очікування =======================
function Waiting({ room, send, onExit, me, serverNow }) {
  const [friends, setFriends] = useState(null)
  const [invited, setInvited] = useState({})
  const free = room.size - room.seats.length
  const quick = !room.private
  const fillIn = room.fill_at && room.status === 'waiting' ? Math.max(0, Math.ceil((room.fill_at * 1000 - serverNow) / 1000)) : null

  useEffect(() => { api('/api/friends').then(setFriends).catch(() => setFriends({ friends: [] })) }, [])

  const share = () => {
    const text = t(
      'Зіграймо в Дурака! {0}',
      room.mode === 'stake' ? t('Ставка {0} фішок.', room.stake) : ''
    )
    const url = `https://t.me/share/url?url=${encodeURIComponent(room.invite)}&text=${encodeURIComponent(text)}`
    if (tg?.openTelegramLink) tg.openTelegramLink(url)
    else navigator.clipboard?.writeText(room.invite)
  }
  const inviteFriend = (f) => {
    send({ type: 'invite', user_id: f.id })
    setInvited((x) => ({ ...x, [f.id]: true }))
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="logo">{quick ? t('Пошук суперників') : room.name}</div>
        <button className="link" onClick={onExit}>{t('Вийти')}</button>
      </header>
      <main className="content">
        <section className="card-box">
          {quick && (
            <div className="searching">
              <div className="radar" />
              <b>{t('Шукаємо гравців…')}</b>
              {fillIn !== null && <small className="hint">{t('гра почнеться не пізніше ніж за') + ' '}{fillIn}{' ' + t('с')}</small>}
            </div>
          )}
          {!quick && fillIn !== null && free > 0 && (
            <p className="hint">{t('Якщо друзі не прийдуть, за {0} с вільні місця займуть інші гравці.', fillIn)}</p>
          )}
          <h3>{room.rules.variant === 'perevodnoy' ? t('Перевідний') : t('Підкидний')} · {room.size}{' ' + t('гравці ·') + ' '}{room.rules.deck_size}{' ' + t('карт')}{room.rules.cheating ? t(' · 🃏 Шулер') : ''}</h3>
          {room.mode === 'stake' ? (
            <div className="terms">
              <div><span>{t('Ставка')}</span><b>{room.terms.stake}</b></div>
              <div><span>{t('Комісія')}</span><b>{room.terms.commission_percent}%</b></div>
              <div><span>{t('Можливий виграш')}</span><b className="plus">+{room.terms.win_share}</b></div>
              <div><span>{t('Можлива втрата')}</span><b className="minus">−{room.terms.max_loss}</b></div>
              {room.rules.cheating && <p className="hint warn">{t('🃏 Увімкнено «Шулер»: боти банку теж мухлюють і ловлять мухлярів — так само, як і ви.')}</p>}
            </div>
          ) : <p className="hint">{t('Безкоштовна гра')}</p>}
          <ul className="seats">
            {room.seats.map((s) => (
              <li key={s.pid}><Avatar url={s.avatar} name={s.name} size={30} /> {s.name}{s.you ? t(' (ви)') : ''}<span className="lvl">{s.lvl}</span>{s.bot && <span className="badge"></span>}</li>
            ))}
            {Array.from({ length: free }).map((_, i) => <li key={i} className="empty">{t('Вільне місце…')}</li>)}
          </ul>
        </section>

        <section className="card-box">
          <h3>{t('Запросити друзів')}</h3>
          {!friends && <div className="spinner" />}
          {friends && friends.friends.length === 0 && <p className="hint">{t('Додайте друзів у вкладці «Друзі».')}</p>}
          <ul className="list">
            {(friends?.friends || []).map((f) => (
              <li key={f.id}>
                <div><b><span className={`online ${f.online ? 'on' : ''}`} />{f.name}</b>
                  <small>{f.online ? t('в мережі') : t('не в мережі — прийде повідомлення в боті')}</small></div>
                <button className="btn small" disabled={invited[f.id]} onClick={() => inviteFriend(f)}>
                  {invited[f.id] ? t('Запрошено') : t('Запросити')}
                </button>
              </li>
            ))}
          </ul>
          <button className="btn" onClick={share}>{t('Поділитися посиланням')}</button>
        </section>

        <section className="card-box">
          <h3>{t('Чат кімнати')}</h3>
          <ChatPanel room={room} me={me} send={send} inline />
        </section>
      </main>
    </div>
  );
}

// ======================= Чат =======================
function ChatPanel({ room, me, send, inline, onClose }) {
  const [text, setText] = useState('')
  const listRef = useRef(null)
  const chat = room.chat || []
  useEffect(() => { listRef.current?.scrollTo(0, 1e6) }, [chat.length])
  const submit = (e) => {
    e.preventDefault()
    if (!text.trim()) return
    send({ type: 'chat', text })
    setText('')
  }
  return (
    <div className={inline ? 'chat inline' : 'chat drawer'}>
      {!inline && <div className="chat-head"><b>{t('Чат')}</b><button className="link" onClick={onClose}>✕</button></div>}
      <div className="chat-list" ref={listRef}>
        {chat.length === 0 && <p className="hint">{t('Поки тихо…')}</p>}
        {chat.map((m, i) => (
          <div key={i} className="chat-msg"><b>{m.name}:</b> {m.emoji ? <span className="big-emoji">{m.emoji}</span> : m.text}</div>
        ))}
      </div>
      <div className="emoji-bar">
        {(me.emojis || []).map((e) => <button key={e} onClick={() => send({ type: 'chat', emoji: e })}>{e}</button>)}
      </div>
      <form className="row" onSubmit={submit}>
        <input value={text} maxLength={200} placeholder={t('Повідомлення…')} onChange={(e) => setText(e.target.value)} />
        <button className="btn small primary" type="submit">➤</button>
      </form>
    </div>
  );
}

// ======================= Стіл =======================
function statusText(game, myId) {
  if (game.status !== 'playing') return ''
  const acts = game.actions
  if (!acts.length) {
    if (game.players.find((p) => p.id === myId)?.out) return t('Ви вийшли з гри 🎉');
    return t('Хід суперника…');
  }
  if (game.defender === myId) return game.taking ? t('Ви берете карти') : t('Відбивайтесь!');
  if (!game.table.length) return t('Ваш хід');
  if (game.taking) return t('Суперник бере — підкиньте або «Пас»');
  return acts.some((a) => a.type === 'pass') ? t('Підкиньте або «Бито»') : t('Можна підкинути');
}

function Table({ data, me, send, left, onExit, onAgain, serverNow, toast }) {
  const [cardOf, setCardOf] = useState(null)
  const { room, game, result, last } = data
  const [sel, setSel] = useState(null)
  const [confirmExit, setConfirmExit] = useState(false)
  const [chatOpen, setChatOpen] = useState(false)
  const [drag, setDrag] = useState(null)
  const [pending, setPending] = useState(null)
  const [ghosts, setGhosts] = useState(null)
  // ширина екрана — щоб уся рука вміщалася без прокрутки
  const [vw, setVw] = useState(() => window.innerWidth)
  // анімація добору з колоди
  const deckRef = useRef(null)
  const deckRect = useRef(null)
  const prevHand = useRef(null)
  const prevCounts = useRef({})
  const prevDeck = useRef(null)
  const [draws, setDraws] = useState(null)
  useEffect(() => {
    const onResize = () => setVw(window.innerWidth)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])
  const dragRef = useRef(null)
  const feltRef = useRef(null)
  const tableRef = useRef(null)
  const handRef = useRef(null)
  const lastDrop = useRef(null)
  const prevShown = useRef(game.table)
  const seen = useRef(game.last_bout?.n)
  const [frozen, setFrozen] = useState(null)

  const myId = game.me
  const names = useMemo(() => Object.fromEntries(room.seats.map((s) => [s.pid, s])), [room.seats])
  const opponents = useMemo(() => {
    const i = game.players.findIndex((p) => p.id === myId)
    return [...game.players.slice(i + 1), ...game.players.slice(0, i)]
  }, [game.players, myId])
  const acts = game.actions
  const myTurn = game.awaited.includes(myId) && acts.length > 0
  const playing = game.status === 'playing'

  // звук/вібрація на початку свого ходу
  const prevTurn = useRef(false)
  useEffect(() => {
    if (myTurn && !prevTurn.current) {
      haptic('medium')
      sfx.play('turn')
    }
    prevTurn.current = myTurn
  }, [myTurn])
  useEffect(() => { setSel(null); setPending(null) }, [game.version])
  useEffect(() => { sfx.play('deal') }, [room.match_id])
  useEffect(() => {
    if (game.status !== 'finished' || !result || result.cancelled) return
    sfx.play(result.draw ? 'tie' : result.loser !== myId ? 'win' : 'lose')
  }, [game.status]) // eslint-disable-line react-hooks/exhaustive-deps

  // ---------- анімації: прилітання карт і змітання столу ----------
  const seatCenter = (pid) => {
    if (pid === myId) {
      const r = handRef.current?.getBoundingClientRect()
      return r ? { x: r.left + r.width / 2, y: r.top + r.height / 2 } : null
    }
    const el = document.querySelector(`[data-pid="${pid}"]`)
    const r = el?.getBoundingClientRect()
    return r ? { x: r.left + r.width / 2, y: r.top + r.height / 2 } : null
  }

  // Стіл, який показуємо: після завершення відбою ще ~1 с тримаємо його «замороженим»,
  // щоб було видно останню кинуту карту, і лише потім змітаємо.
  const shown = frozen ? frozen.table : game.table
  const shownKey = JSON.stringify(shown)

  useLayoutEffect(() => {
    const was = new Set(prevShown.current.flat().filter(Boolean))
    const nowCards = shown.flat().filter(Boolean)
    // нові карти на столі прилітають від того, хто їх кинув
    // відбилися — «ляп» поверх карти; підкинули до наявних — легкий кидок; перша карта відбою — звичайний
    const fresh = shown.flatMap((pair, i) => pair.map((c, j) => (c && !was.has(c) ? j : -1))).filter((j) => j >= 0)
    if (fresh.length) sfx.play(fresh.includes(1) ? 'defend' : was.size ? 'throw' : 'card')
    for (const c of nowCards) {
      if (was.has(c)) continue
      const el = tableRef.current?.querySelector(`[data-card="${c}"]`)
      if (!el) continue
      const r = el.getBoundingClientRect()
      let from = null
      if (lastDrop.current?.card === c) from = { x: lastDrop.current.x, y: lastDrop.current.y }
      else if (last?.card === c) from = seatCenter(last.player)
      if (!from) continue
      const dx = from.x - (r.left + r.width / 2)
      const dy = from.y - (r.top + r.height / 2)
      el.animate([
        { transform: `translate(${dx}px, ${dy}px) rotate(${dx > 0 ? 18 : -18}deg) scale(1.12)`, boxShadow: '0 18px 30px rgba(0,0,0,.5)' },
        { transform: 'translate(0,0) rotate(0) scale(1)', boxShadow: '0 2px 5px rgba(0,0,0,.35)' },
      ], { duration: 340, easing: 'cubic-bezier(.2,.9,.25,1.15)' })
    }
    prevShown.current = shown
    lastDrop.current = null
  }, [shownKey]) // eslint-disable-line react-hooks/exhaustive-deps

  const sweep = (fz) => {
    const items = []
    tableRef.current?.querySelectorAll('[data-card]').forEach((el) => {
      const r = el.getBoundingClientRect()
      items.push({ card: el.dataset.card, left: r.left, top: r.top })
    })
    const target = fz.took ? seatCenter(fz.defender) : { x: window.innerWidth + 80, y: window.innerHeight * 0.4 }
    sfx.play(fz.took ? 'take' : 'beaten')
    setFrozen(null)
    if (target && items.length) {
      setGhosts({ items, target, took: fz.took })
      setTimeout(() => setGhosts(null), 520)
    }
  }

  useLayoutEffect(() => {
    const lb = game.last_bout
    if (lb && lb.n !== seen.current) {
      seen.current = lb.n
      if (!game.table.length) setFrozen(lb)
    }
    // новий відбій почався раніше, ніж минула пауза — змітаємо одразу
    if (game.table.length && frozen) sweep(frozen)
  }, [game.version]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!frozen) return
    const timer = setTimeout(() => sweep(frozen), 950)
    return () => clearTimeout(timer)
  }, [frozen]) // eslint-disable-line react-hooks/exhaustive-deps

  // результат «Спіймати» (режим «Шулер»)
  const [catchMsg, setCatchMsg] = useState(null)
  useEffect(() => {
    if (last?.type !== 'catch') return
    const who = names[last.player]?.name
    const cheater = names[last.cheater]?.name
    setCatchMsg(last.caught
      ? { ok: true, text: last.cheater === myId ? t('Вас спіймали на мухлюванні!') : t('{0} спіймав мухляра: {1}', who, cheater) }
      : { ok: false, text: last.player === myId ? t('Мухлювання не було') : t('{0}: хибна тривога', who) })
    if (last.caught) { haptic('heavy'); sfx.play('catch') }
    const timer = setTimeout(() => setCatchMsg(null), 2200)
    return () => clearTimeout(timer)
  }, [last?.n]) // eslint-disable-line react-hooks/exhaustive-deps

  useLayoutEffect(() => {
    if (!ghosts) return
    document.querySelectorAll('.ghost').forEach((el, i) => {
      const r = el.getBoundingClientRect()
      const dx = ghosts.target.x - (r.left + r.width / 2)
      const dy = ghosts.target.y - (r.top + r.height / 2)
      el.animate([
        { transform: 'none', opacity: 1 },
        { transform: `translate(${dx}px, ${dy}px) rotate(${ghosts.took ? 0 : 40}deg) scale(${ghosts.took ? 0.6 : 0.9})`, opacity: ghosts.took ? 0.2 : 0 },
      ], { duration: 450, delay: i * 25, easing: 'cubic-bezier(.4,0,.6,1)', fill: 'forwards' })
    })
  }, [ghosts])

  // ---------- дії ----------
  const act = (a) => {
    haptic('light')
    send({ type: 'action', room: room.id, action: a, version: game.version })
    if (a.card) setPending(a.card)
    setSel(null)
  }
  const cardActs = (c) => acts.filter((a) => a.card === c && a.type !== 'catch')
  const tapCard = (c) => {
    const opts = cardActs(c)
    if (!opts.length) return
    const targets = new Set(opts.filter((a) => a.type === 'defend').map((a) => a.target))
    if (opts.length === 1 || opts.every((a) => a.type === 'attack')) return act(opts[0])
    if (targets.size === 1 && !opts.some((a) => a.type === 'transfer')) return act(opts[0])
    setSel(sel === c ? null : c)
  }
  const tapTable = (i, card) => {
    if (frozen) return
    if (sel) {
      const a = acts.find((x) => x.type === 'defend' && x.card === sel && x.target === i)
      if (a) act(a)
      return
    }
    // «Шулер»: торкнутися чужої карти — спіймати мухлювання
    const c = acts.find((x) => x.type === 'catch' && x.card === card)
    if (c) act(c)
  }

  // ---------- drag-and-drop ----------
  const onDown = (e, c) => {
    if (!playing || pending) return
    e.currentTarget.setPointerCapture?.(e.pointerId)
    dragRef.current = { card: c, x0: e.clientX, y0: e.clientY, x: e.clientX, y: e.clientY, moved: false }
    setDrag({ ...dragRef.current })
  }
  const onMove = (e) => {
    const d = dragRef.current
    if (!d) return
    d.x = e.clientX
    d.y = e.clientY
    if (!d.moved && Math.hypot(d.x - d.x0, d.y - d.y0) > 8) { d.moved = true; haptic('light') }
    setDrag({ ...d })
  }
  const onUp = () => {
    const d = dragRef.current
    dragRef.current = null
    setDrag(null)
    if (!d) return
    if (!d.moved) return tapCard(d.card)
    const felt = feltRef.current.getBoundingClientRect()
    const handTop = handRef.current.getBoundingClientRect().top
    const pairEls = [...(tableRef.current?.querySelectorAll('.pair') || [])]
    const rects = pairEls.map((el) => el.getBoundingClientRect())
    const over = rects.findIndex((r) => inside(r, d.x, d.y, 12))
    // кинути можна й «махом»: достатньо винести карту вище руки
    const onTable = inside(felt, d.x, d.y) || d.y < handTop - 30
    const a = resolveDrop(acts, d.card, { onTable, overPair: over >= 0 ? over : null, nearest: nearestPairs(rects, d.x, d.y) })
    if (a) {
      lastDrop.current = { card: d.card, x: d.x, y: d.y }
      act(a)
    } else if (onTable && cardActs(d.card).length === 0) {
      haptic('rigid')
    }
  }

  const selTransfer = sel && acts.find((a) => a.type === 'transfer' && a.card === sel)
  const selTargets = new Set(sel ? acts.filter((a) => a.type === 'defend' && a.card === sel).map((a) => a.target) : [])
  const dragTargets = new Set(drag?.moved ? acts.filter((a) => a.type === 'defend' && a.card === drag.card).map((a) => a.target) : [])
  const take = acts.find((a) => a.type === 'take')
  const pass = acts.find((a) => a.type === 'pass')
  const total = room.rules.turn_seconds * 1000

  // бульбашки чату над гравцями (3 секунди)
  const bubbles = {}
  for (const m of room.chat || []) if (serverNow / 1000 - m.ts < 3.5) bubbles[m.pid] = m

  // скільки карти «виглядає» з-під сусідньої: що більше карт, то щільніше (але кут з рангом видно завжди)
  const CARD_W = 56
  const handN = game.hand.length
  const handAvail = Math.min(vw, 640) - 20
  const handStep = handN > 1 ? Math.max(16, Math.min(42, (handAvail - CARD_W) / (handN - 1))) : 0
  const handFits = handN <= 1 || CARD_W + handStep * (handN - 1) <= handAvail

  // ---------- карти летять з колоди: у руку (лицем) і суперникам (сорочкою) ----------
  useLayoutEffect(() => {
    const deckEl = deckRef.current
    if (deckEl) {
      const r = deckEl.getBoundingClientRect()
      deckRect.current = { x: r.left + r.width / 2, y: r.top + r.height / 2 }
    }
    const from = deckRect.current
    const first = prevHand.current === null
    const firstDeal = first && game.bout === 1 && !game.table.length && game.discard_count === 0
    const drew = !first && prevDeck.current !== null && game.deck_count < prevDeck.current
    if ((firstDeal || drew) && from) {
      const lb = game.last_bout
      const taker = !firstDeal && lb?.took ? lb.defender : null
      const taken = taker ? lb.table.flat().filter(Boolean) : []
      // після відбою стіл ще ~1 с «заморожений» — карти з колоди летять уже після нього
      const delay0 = firstDeal ? 150 : 1050
      const mineNew = game.hand.filter((c) => (firstDeal || !prevHand.current.has(c)) && !(taker === myId && taken.includes(c)))
      mineNew.forEach((c, i) => {
        const el = handRef.current?.querySelector(`[data-card="${c}"]`)
        if (!el) return
        const r = el.getBoundingClientRect()
        const dx = from.x - (r.left + r.width / 2)
        const dy = from.y - (r.top + r.height / 2)
        el.animate([
          { transform: `translate(${dx}px, ${dy}px) rotate(-12deg) scale(.85)`, filter: 'brightness(.6)' },
          { transform: 'translate(0,0) rotate(0) scale(1)', filter: 'none' },
        ], { duration: 380, delay: delay0 + i * 110, easing: 'cubic-bezier(.2,.8,.25,1)', fill: 'backwards' })
      })
      const flights = []
      opponents.forEach((p, k) => {
        const before = firstDeal ? 0 : (prevCounts.current[p.id] ?? p.cards)
        const n = p.cards - before - (taker === p.id ? taken.length : 0)
        const to = seatCenter(p.id)
        if (n <= 0 || !to) return
        for (let j = 0; j < n; j++) flights.push({ id: `${p.id}-${j}`, from, to, delay: delay0 + (k * 2 + j) * 90 })
      })
      if (flights.length) {
        setDraws(flights)
        const maxDelay = Math.max(...flights.map((f) => f.delay))
        setTimeout(() => setDraws(null), maxDelay + 600)
      }
      if (!firstDeal) {
        // кожна карта з колоди — окремий тихий «шурх» у такт анімації
        const times = [...mineNew.map((_, i) => delay0 + i * 110), ...flights.map((f) => f.delay)].sort((a, b) => a - b).slice(0, 10)
        times.forEach((ms) => sfx.play('draw', ms / 1000))
      }
    }
    prevHand.current = new Set(game.hand)
    prevCounts.current = Object.fromEntries(game.players.map((p) => [p.id, p.cards]))
    prevDeck.current = game.deck_count
  }, [game.version]) // eslint-disable-line react-hooks/exhaustive-deps

  useLayoutEffect(() => {
    if (!draws) return
    document.querySelectorAll('.draw-back').forEach((el) => {
      const f = draws.find((x) => x.id === el.dataset.id)
      if (!f) return
      el.animate([
        { transform: 'translate(-50%, -50%) scale(.9)', opacity: 1 },
        { transform: `translate(calc(-50% + ${f.to.x - f.from.x}px), calc(-50% + ${f.to.y - f.from.y}px)) scale(.5)`, opacity: 0.2 },
      ], { duration: 420, delay: f.delay, easing: 'cubic-bezier(.3,.7,.3,1)', fill: 'both' })
    })
  }, [draws])

  const won = result && !result.cancelled && !result.draw && result.loser !== myId

  return (
    <div className={`table-screen tb-${me.cosmetics?.table || 'table_green'}`} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp}>
      <div className="opponents">
        {opponents.map((p) => {
          const s = names[p.id] || {}
          const waiting = playing && game.awaited.includes(p.id)
          return (
            <div key={p.id} data-pid={p.id} className={`opp ${waiting ? 'turn' : ''} ${p.out ? 'out' : ''}`}>
              {bubbles[p.id] && <div className="bubble">{bubbles[p.id].emoji || bubbles[p.id].text}</div>}
              <div className="opp-head">
                <div className="opp-ava" onClick={() => setCardOf(s)}><Avatar url={s.avatar} name={s.name} size={30} /><span className="lvl">{s.lvl}</span></div>
                <div className="opp-name">{s.bot ? ' ' : ''}{s.name}</div>
              </div>
              <Backs n={p.cards} back={s.back} />
              <div className="opp-meta">
                {p.cards}{' ' + t('карт')}{game.attacker === p.id && playing && <span className="tag atk">{t('атакує')}</span>}
                {game.defender === p.id && playing && <span className="tag def">{game.taking ? t('бере') : t('б\'ється')}</span>}
                {p.passed && <span className="tag">{t('пас')}</span>}
                {p.out && <span className="tag win">{t('вийшов')}</span>}
              </div>
              {waiting && <div className="timer"><i style={{ width: `${(left / total) * 100}%` }} /></div>}
            </div>
          );
        })}
      </div>

      <div className={`felt ${drag?.moved ? 'drop-hint' : ''}`} ref={feltRef}>
        <div className="deck-zone">
          {game.deck_count > 0 ? (
            <div className="deck" ref={deckRef}>
              <div className="trump-under"><Card c={game.trump_card} small /></div>
              <div className={`back big cb-${me.cosmetics?.back || 'back_classic'}`} />
              <span className="count">{game.deck_count}</span>
            </div>
          ) : null}
          <div className={`trump-badge ${game.trump === 'H' || game.trump === 'D' ? 'red' : ''}`} title={t('Козир')}>
            <span>{SUIT[game.trump]}</span><small>{t('козир')}</small>
          </div>
          <div className="discard">{t('Бито:') + ' '}{game.discard_count}</div>
        </div>
        <div className="table-cards" ref={tableRef}>
          {shown.map(([a, d], i) => (
            <div key={a} className={`pair ${!frozen && (selTargets.has(i) || dragTargets.has(i)) ? 'target' : ''}`}>
              <Card c={a} onClick={() => tapTable(i, a)} />
              {d && <div className="cover"><Card c={d} onClick={(e) => { e.stopPropagation(); tapTable(i, d) }} /></div>}
            </div>
          ))}
          {!shown.length && playing && <div className="table-hint">{names[game.attacker]?.name}{' ' + t('ходить')}</div>}
        </div>
      </div>

      <div className="me-zone">
        {bubbles[myId] && <div className="bubble mine">{bubbles[myId].emoji || bubbles[myId].text}</div>}
        <div className={`status ${myTurn ? 'mine' : ''}`}>
          {statusText(game, myId)}
          {myTurn && <span className="secs">{Math.ceil(left / 1000)}{t('с')}</span>}
        </div>
        {myTurn && <div className="timer mine"><i style={{ width: `${(left / total) * 100}%` }} /></div>}
        <div className="buttons">
          {selTransfer && <button className="btn primary" onClick={() => act(selTransfer)}>{t('Перевести')}</button>}
          {take && <button className="btn warn" onClick={() => act(take)}>{t('Беру')}</button>}
          {pass && <button className="btn primary" onClick={() => act(pass)}>{game.taking ? t('Пас') : t('Бито')}</button>}
        </div>
        <div className={`hand ${handFits ? '' : 'scroll'}`} ref={handRef}>
          {game.hand.map((c, i) => {
            const mine = cardActs(c).filter((a) => a.type !== 'catch')
            const playable = mine.some((a) => !a.cheat)
            const cheatable = !playable && mine.length > 0
            const dragging = drag?.card === c && drag.moved
            const style = {
              marginLeft: i === 0 ? 0 : handStep - CARD_W,
              ...(dragging ? { transform: `translate(${drag.x - drag.x0}px, ${drag.y - drag.y0}px) rotate(${(drag.x - drag.x0) / 25}deg) scale(1.15)` } : {}),
            }
            return (
              <Card key={c} c={c}
                className={`${sel === c ? 'sel' : ''} ${playable ? 'play' : ''} ${cheatable ? 'cheaty' : ''} ${myTurn && !playable && !cheatable ? 'dim' : ''} ${dragging ? 'dragging' : ''} ${pending === c ? 'pending' : ''}`}
                style={style}
                onPointerDown={(e) => onDown(e, c)} />
            )
          })}
        </div>
        <div className="me-bar">
          <span>{me.name}{room.mode === 'stake' ? <>{' ' + t('· ставка') + ' '}{room.stake} <Chip /></> : ''}</span>
          <span>
            <button className="link" onClick={() => setChatOpen(true)}>{t('💬 Чат')}</button>
            {playing && <button className="link" onClick={() => setConfirmExit(true)}>{t('Здатися')}</button>}
          </span>
        </div>
      </div>

      <div className="quick-emoji">
        {(me.emojis || []).slice(0, 4).map((e) => <button key={e} onClick={() => send({ type: 'chat', emoji: e })}>{e}</button>)}
      </div>

      {catchMsg && <div className={`catch-banner ${catchMsg.ok ? 'ok' : ''}`}>{catchMsg.ok ? '🚨 ' : '🤷 '}{catchMsg.text}</div>}
      {room.rules.cheating && playing && <div className="cheat-hint">{t('🃏 Шулер: торкніться підозрілої карти, щоб спіймати')}</div>}

      {draws && draws.map((f) => (
        <div key={f.id} data-id={f.id} className={`back draw-back cb-${me.cosmetics?.back || 'back_classic'}`}
          style={{ position: 'fixed', left: f.from.x, top: f.from.y, zIndex: 31 }} />
      ))}

      {ghosts && ghosts.items.map((g) => (
        <Card key={g.card} c={g.card} className="ghost" style={{ position: 'fixed', left: g.left, top: g.top, margin: 0, zIndex: 30 }} />
      ))}

      {chatOpen && <div className="overlay bottom" onClick={() => setChatOpen(false)}>
        <div onClick={(e) => e.stopPropagation()} style={{ width: '100%' }}>
          <ChatPanel room={room} me={me} send={send} onClose={() => setChatOpen(false)} />
        </div>
      </div>}

      {confirmExit && playing && (
        <div className="overlay">
          <div className="modal">
            <h3>{t('Здатися?')}</h3>
            <p>{t('Ви будете «дурнем» у цьому матчі')}{room.mode === 'stake' ? t(' і втратите ставку {0}', room.stake) : ''}.</p>
            <div className="actions-col">
              <button className="btn warn" onClick={() => { setConfirmExit(false); send({ type: 'surrender' }) }}>{t('Так, здатися')}</button>
              <button className="btn" onClick={() => setConfirmExit(false)}>{t('Грати далі')}</button>
            </div>
          </div>
        </div>
      )}

      {!playing && won && <Victory id={me.cosmetics?.victory || 'victory_stars'} />}
      {!playing && result && !cardOf && <ResultModal result={result} myId={myId} names={names} onExit={onExit} onAgain={onAgain} room={room} send={send} />}
      {cardOf && <PlayerCard seat={cardOf} matchId={room.match_id} onClose={() => setCardOf(null)} toast={toast} />}
    </div>
  );
}

function ResultModal({ result, myId, names, onExit, onAgain, room, send }) {
  const [asked, setAsked] = useState(false)
  if (result.cancelled) {
    return (
      <div className="overlay"><div className="modal">
          <h2>{t('Матч скасовано')}</h2><p>{result.reason}</p><p className="hint">{t('Ставки повернуто.')}</p>
          <button className="btn primary" onClick={onExit}>{t('В меню')}</button>
        </div></div>
    );
  }
  const lost = result.loser === myId
  const delta = result.payouts?.[myId]
  return (
    <div className="overlay">
      <div className="modal">
        <h2>{result.draw ? t('🤝 Нічия') : lost ? t('🃏 Ви дурень') : t('🏆 Перемога!')}</h2>
        {!result.draw && !lost && <p>{t('Дурень:') + ' '}{names[result.loser]?.name}</p>}
        {result.surrendered && <p className="hint">{names[result.surrendered]?.name}{' ' + t('здався')}</p>}
        {delta !== undefined && <p className={delta >= 0 ? 'plus big' : 'minus big'}>{delta >= 0 ? '+' : ''}{delta} <Chip /></p>}
        {room.ranked && <p className="hint">{t('Рейтингова гра — рейтинг оновлено')}</p>}
        <p className="hint">{t('Матч') + ' '}{room.match_id}</p>
        <div className="actions-col">
          {room.tournament ? (
            <button className="btn primary" onClick={onExit}>{t('До турніру')}</button>
          ) : (
            <>
              <button className="btn primary" disabled={asked}
                onClick={() => { setAsked(true); send({ type: 'rematch', room: room.id }) }}>
                {asked ? t('Чекаємо суперників…') : t('🔁 Реванш')}
              </button>
              {room.rematch?.length > 0 && <p className="hint">{t('За реванш:') + ' '}{room.rematch.join(', ')}</p>}
              <button className="btn" onClick={onAgain}>{t('Нова гра')}</button>
            </>
          )}
          <button className="btn" onClick={onExit}>{t('В меню')}</button>
        </div>
      </div>
    </div>
  );
}
