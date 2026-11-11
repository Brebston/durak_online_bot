import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { api, beep, haptic, rankOf, suitOf, SUIT, tg } from '../api.js'
import { inside, nearestPairs, resolveDrop } from '../dnd.js'
import { Victory } from '../Fx.jsx'

const LEVELS = [['easy', 'Легкий'], ['medium', 'Середній'], ['hard', 'Сильний']]
const RANKS = { 11: 'В', 12: 'Д', 13: 'К', 14: 'Т' }

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
    const t = setInterval(() => setNow(Date.now()), 250)
    return () => clearInterval(t)
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
  return <Table data={data} me={me} send={send} left={left} onExit={onExit} onAgain={onAgain} serverNow={serverNow} />
}

// ======================= Очікування =======================
function Waiting({ room, send, onExit, me, serverNow }) {
  const [level, setLevel] = useState('medium')
  const [friends, setFriends] = useState(null)
  const [invited, setInvited] = useState({})
  const free = room.size - room.seats.length
  const quick = !room.private
  const fillIn = room.fill_at ? Math.max(0, Math.ceil((room.fill_at * 1000 - serverNow) / 1000)) : null

  useEffect(() => { api('/api/friends').then(setFriends).catch(() => setFriends({ friends: [] })) }, [])

  const share = () => {
    const text = `Зіграймо в Дурака! ${room.mode === 'stake' ? `Ставка ${room.stake} фішок.` : ''}`
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
        <div className="logo">{quick ? 'Пошук суперників' : room.name}</div>
        <button className="link" onClick={onExit}>Вийти</button>
      </header>
      <main className="content">
        <section className="card-box">
          {quick && (
            <div className="searching">
              <div className="radar" />
              <b>Шукаємо гравців…</b>
              {fillIn !== null && <small className="hint">гра почнеться не пізніше ніж за {fillIn} с</small>}
            </div>
          )}
          <h3>{room.rules.variant === 'perevodnoy' ? 'Перевідний' : 'Підкидний'} · {room.size} гравці · {room.rules.deck_size} карт</h3>
          {room.mode === 'stake' ? (
            <div className="terms">
              <div><span>Ставка</span><b>{room.terms.stake}</b></div>
              <div><span>Комісія</span><b>{room.terms.commission_percent}%</b></div>
              <div><span>Можливий виграш</span><b className="plus">+{room.terms.win_share}</b></div>
              <div><span>Можлива втрата</span><b className="minus">−{room.terms.max_loss}</b></div>
            </div>
          ) : <p className="hint">Безкоштовна гра</p>}
          <ul className="seats">
            {room.seats.map((s) => (
              <li key={s.pid}><div className={`mini-back cb-${s.back}`} /> {s.name}{s.you ? ' (ви)' : ''}{s.bot && <span className="badge">🤖</span>}</li>
            ))}
            {Array.from({ length: free }).map((_, i) => <li key={i} className="empty">Вільне місце…</li>)}
          </ul>
        </section>

        <section className="card-box">
          <h3>Запросити друзів</h3>
          {!friends && <div className="spinner" />}
          {friends && friends.friends.length === 0 && <p className="hint">Додайте друзів у вкладці «Друзі».</p>}
          <ul className="list">
            {(friends?.friends || []).map((f) => (
              <li key={f.id}>
                <div><b><span className={`online ${f.online ? 'on' : ''}`} />{f.name}</b>
                  <small>{f.online ? 'в мережі' : 'не в мережі — прийде повідомлення в боті'}</small></div>
                <button className="btn small" disabled={invited[f.id]} onClick={() => inviteFriend(f)}>
                  {invited[f.id] ? 'Запрошено' : 'Запросити'}
                </button>
              </li>
            ))}
          </ul>
          <button className="btn" onClick={share}>Поділитися посиланням</button>
        </section>

        {!quick && room.owner && (
          <section className="card-box">
            <h3>Додати ботів на вільні місця</h3>
            <div className="seg">
              {LEVELS.map(([v, l]) => <button key={v} className={level === v ? 'on' : ''} onClick={() => setLevel(v)}>{l}</button>)}
            </div>
            <div className="actions-col">
              <button className="btn primary" onClick={() => send({ type: 'add_bots', room: room.id, level })}>
                Заповнити ботами ({free})
              </button>
            </div>
          </section>
        )}

        <section className="card-box">
          <h3>Чат кімнати</h3>
          <ChatPanel room={room} me={me} send={send} inline />
        </section>
      </main>
    </div>
  )
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
      {!inline && <div className="chat-head"><b>Чат</b><button className="link" onClick={onClose}>✕</button></div>}
      <div className="chat-list" ref={listRef}>
        {chat.length === 0 && <p className="hint">Поки тихо…</p>}
        {chat.map((m, i) => (
          <div key={i} className="chat-msg"><b>{m.name}:</b> {m.emoji ? <span className="big-emoji">{m.emoji}</span> : m.text}</div>
        ))}
      </div>
      <div className="emoji-bar">
        {(me.emojis || []).map((e) => <button key={e} onClick={() => send({ type: 'chat', emoji: e })}>{e}</button>)}
      </div>
      <form className="row" onSubmit={submit}>
        <input value={text} maxLength={200} placeholder="Повідомлення…" onChange={(e) => setText(e.target.value)} />
        <button className="btn small primary" type="submit">➤</button>
      </form>
    </div>
  )
}

// ======================= Стіл =======================
function statusText(game, myId) {
  if (game.status !== 'playing') return ''
  const acts = game.actions
  if (!acts.length) {
    if (game.players.find((p) => p.id === myId)?.out) return 'Ви вийшли з гри 🎉'
    return 'Хід суперника…'
  }
  if (game.defender === myId) return game.taking ? 'Ви берете карти' : 'Відбивайтесь!'
  if (!game.table.length) return 'Ваш хід'
  if (game.taking) return 'Суперник бере — підкиньте або «Пас»'
  return acts.some((a) => a.type === 'pass') ? 'Підкиньте або «Бито»' : 'Можна підкинути'
}

function Table({ data, me, send, left, onExit, onAgain, serverNow }) {
  const { room, game, result, last } = data
  const [sel, setSel] = useState(null)
  const [confirmExit, setConfirmExit] = useState(false)
  const [chatOpen, setChatOpen] = useState(false)
  const [drag, setDrag] = useState(null)
  const [pending, setPending] = useState(null)
  const [ghosts, setGhosts] = useState(null)
  const dragRef = useRef(null)
  const feltRef = useRef(null)
  const tableRef = useRef(null)
  const handRef = useRef(null)
  const lastDrop = useRef(null)
  const prev = useRef({ table: [], rects: {}, defender: null })
  const seen = useRef(0)

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
      if (me.settings.sound) beep()
    }
    prevTurn.current = myTurn
  }, [myTurn, me.settings.sound])
  useEffect(() => { setSel(null); setPending(null) }, [game.version])

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

  useLayoutEffect(() => {
    const was = new Set(prev.current.table.flat().filter(Boolean))
    const nowCards = game.table.flat().filter(Boolean)
    // нові карти на столі прилітають від того, хто їх кинув
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
      ], { duration: 320, easing: 'cubic-bezier(.2,.9,.25,1.15)' })
    }
    // стіл очистився: «бито» — карти відлітають убік, «беру» — до захисника
    if (prev.current.table.length && !game.table.length && last && last.n !== seen.current) {
      seen.current = last.n
      const took = last.bout_end === 'take'
      const target = took ? seatCenter(prev.current.defender) : { x: window.innerWidth + 80, y: window.innerHeight * 0.4 }
      const items = Object.entries(prev.current.rects).map(([card, r]) => ({ card, ...r }))
      if (target && items.length) {
        setGhosts({ items, target, took })
        setTimeout(() => setGhosts(null), 520)
      }
    }
    // запамʼятовуємо позиції для наступного кадру
    const rects = {}
    tableRef.current?.querySelectorAll('[data-card]').forEach((el) => {
      const r = el.getBoundingClientRect()
      rects[el.dataset.card] = { left: r.left, top: r.top }
    })
    prev.current = { table: game.table, rects, defender: game.defender }
    lastDrop.current = null
  }, [game.version]) // eslint-disable-line react-hooks/exhaustive-deps

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
  const cardActs = (c) => acts.filter((a) => a.card === c)
  const tapCard = (c) => {
    const opts = cardActs(c)
    if (!opts.length) return
    const targets = new Set(opts.filter((a) => a.type === 'defend').map((a) => a.target))
    if (opts.length === 1 || opts.every((a) => a.type === 'attack')) return act(opts[0])
    if (targets.size === 1 && !opts.some((a) => a.type === 'transfer')) return act(opts[0])
    setSel(sel === c ? null : c)
  }
  const tapTable = (i) => {
    if (!sel) return
    const a = acts.find((x) => x.type === 'defend' && x.card === sel && x.target === i)
    if (a) act(a)
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
              <div className="opp-name">{s.bot ? '🤖 ' : ''}{s.name}</div>
              <Backs n={p.cards} back={s.back} />
              <div className="opp-meta">
                {p.cards} карт
                {game.attacker === p.id && playing && <span className="tag atk">атакує</span>}
                {game.defender === p.id && playing && <span className="tag def">{game.taking ? 'бере' : 'б\'ється'}</span>}
                {p.passed && <span className="tag">пас</span>}
                {p.out && <span className="tag win">вийшов</span>}
              </div>
              {waiting && <div className="timer"><i style={{ width: `${(left / total) * 100}%` }} /></div>}
            </div>
          )
        })}
      </div>

      <div className={`felt ${drag?.moved ? 'drop-hint' : ''}`} ref={feltRef}>
        <div className="deck-zone">
          {game.deck_count > 0 ? (
            <div className="deck">
              <div className="trump-under"><Card c={game.trump_card} small /></div>
              <div className={`back big cb-${me.cosmetics?.back || 'back_classic'}`} />
              <span className="count">{game.deck_count}</span>
            </div>
          ) : <div className="trump-only">Козир {SUIT[game.trump]}</div>}
          <div className="discard">Бито: {game.discard_count}</div>
        </div>
        <div className="table-cards" ref={tableRef}>
          {game.table.map(([a, d], i) => (
            <div key={a} className={`pair ${selTargets.has(i) || dragTargets.has(i) ? 'target' : ''}`} onClick={() => tapTable(i)}>
              <Card c={a} />
              {d && <div className="cover"><Card c={d} /></div>}
            </div>
          ))}
          {!game.table.length && playing && <div className="table-hint">{names[game.attacker]?.name} ходить</div>}
        </div>
      </div>

      <div className="me-zone">
        {bubbles[myId] && <div className="bubble mine">{bubbles[myId].emoji || bubbles[myId].text}</div>}
        <div className={`status ${myTurn ? 'mine' : ''}`}>
          {statusText(game, myId)}
          {myTurn && <span className="secs">{Math.ceil(left / 1000)}с</span>}
        </div>
        {myTurn && <div className="timer mine"><i style={{ width: `${(left / total) * 100}%` }} /></div>}
        <div className="buttons">
          {selTransfer && <button className="btn primary" onClick={() => act(selTransfer)}>Перевести</button>}
          {take && <button className="btn warn" onClick={() => act(take)}>Беру</button>}
          {pass && <button className="btn primary" onClick={() => act(pass)}>{game.taking ? 'Пас' : 'Бито'}</button>}
        </div>
        <div className="hand" ref={handRef}>
          {game.hand.map((c) => {
            const playable = cardActs(c).length > 0
            const dragging = drag?.card === c && drag.moved
            const style = dragging
              ? { transform: `translate(${drag.x - drag.x0}px, ${drag.y - drag.y0}px) rotate(${(drag.x - drag.x0) / 25}deg) scale(1.15)` }
              : undefined
            return (
              <Card key={c} c={c}
                className={`${sel === c ? 'sel' : ''} ${playable ? 'play' : ''} ${myTurn && !playable ? 'dim' : ''} ${dragging ? 'dragging' : ''} ${pending === c ? 'pending' : ''}`}
                style={style}
                onPointerDown={(e) => onDown(e, c)} />
            )
          })}
        </div>
        <div className="me-bar">
          <span>{me.name} · козир {SUIT[game.trump]}{room.mode === 'stake' ? ` · ставка ${room.stake}` : ''}</span>
          <span>
            <button className="link" onClick={() => setChatOpen(true)}>💬 Чат</button>
            {playing && <button className="link" onClick={() => setConfirmExit(true)}>Здатися</button>}
          </span>
        </div>
      </div>

      <div className="quick-emoji">
        {(me.emojis || []).slice(0, 4).map((e) => <button key={e} onClick={() => send({ type: 'chat', emoji: e })}>{e}</button>)}
      </div>

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
            <h3>Здатися?</h3>
            <p>Ви будете «дурнем» у цьому матчі{room.mode === 'stake' ? ` і втратите ставку ${room.stake}` : ''}.</p>
            <div className="actions-col">
              <button className="btn warn" onClick={() => { setConfirmExit(false); send({ type: 'surrender' }) }}>Так, здатися</button>
              <button className="btn" onClick={() => setConfirmExit(false)}>Грати далі</button>
            </div>
          </div>
        </div>
      )}

      {!playing && won && <Victory id={me.cosmetics?.victory || 'victory_stars'} />}
      {!playing && result && <ResultModal result={result} myId={myId} names={names} onExit={onExit} onAgain={onAgain} room={room} />}
    </div>
  )
}

function ResultModal({ result, myId, names, onExit, onAgain, room }) {
  if (result.cancelled) {
    return (
      <div className="overlay"><div className="modal">
        <h2>Матч скасовано</h2><p>{result.reason}</p><p className="hint">Ставки повернуто.</p>
        <button className="btn primary" onClick={onExit}>В меню</button>
      </div></div>
    )
  }
  const lost = result.loser === myId
  const delta = result.payouts?.[myId]
  return (
    <div className="overlay">
      <div className="modal">
        <h2>{result.draw ? '🤝 Нічия' : lost ? '🃏 Ви дурень' : '🏆 Перемога!'}</h2>
        {!result.draw && !lost && <p>Дурень: {names[result.loser]?.name}</p>}
        {result.surrendered && <p className="hint">{names[result.surrendered]?.name} здався</p>}
        {delta !== undefined && <p className={delta >= 0 ? 'plus big' : 'minus big'}>{delta >= 0 ? '+' : ''}{delta} фішок</p>}
        <p className="hint">Матч {room.match_id}</p>
        <div className="actions-col">
          <button className="btn primary" onClick={onAgain}>Ще раз</button>
          <button className="btn" onClick={onExit}>В меню</button>
        </div>
      </div>
    </div>
  )
}
