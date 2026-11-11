import React, { useCallback, useEffect, useState } from 'react'
import { api, label } from '../api.js'
import { Chip } from '../Fx.jsx'

const SECTIONS = [['overview', 'Огляд'], ['balance', 'Баланси'], ['withdrawals', 'Виведення'], ['matches', 'Матчі'], ['tickets', 'Звернення'], ['modes', 'Режими'], ['audit', 'Аудит']]
const ts = (t) => new Date(t * 1000).toLocaleString('uk-UA')

// window.prompt не працює в деяких клієнтах Telegram — власне модальне вікно
let openAsk = null
function ask(title) {
  return new Promise((resolve) => openAsk?.(title, resolve))
}
function AskModal() {
  const [st, setSt] = useState(null)
  const [v, setV] = useState('')
  useEffect(() => { openAsk = (title, resolve) => { setV(''); setSt({ title, resolve }) } }, [])
  if (!st) return null
  const done = (val) => { st.resolve(val); setSt(null) }
  return (
    <div className="overlay"><div className="modal">
      <h3>{st.title}</h3>
      <textarea autoFocus value={v} onChange={(e) => setV(e.target.value)} />
      <div className="actions-col">
        <button className="btn primary" disabled={v.trim().length < 3} onClick={() => done(v.trim())}>OK</button>
        <button className="btn" onClick={() => done(null)}>Скасувати</button>
      </div>
    </div></div>
  )
}

export default function Admin({ me, toast, reloadMe }) {
  const [sec, setSec] = useState('overview')
  return (
    <div className="admin">
      <AskModal />
      <div className="seg wrap">
        {SECTIONS.map(([id, n]) => <button key={id} className={sec === id ? 'on' : ''} onClick={() => setSec(id)}>{n}</button>)}
      </div>
      {sec === 'overview' && <Overview toast={toast} />}
      {sec === 'balance' && <Balances toast={toast} reloadMe={reloadMe} />}
      {sec === 'withdrawals' && <Withdrawals toast={toast} />}
      {sec === 'matches' && <Matches toast={toast} />}
      {sec === 'tickets' && <Tickets toast={toast} />}
      {sec === 'modes' && <Modes toast={toast} reloadMe={reloadMe} />}
      {sec === 'audit' && <Audit toast={toast} />}
    </div>
  )
}

function Overview({ toast }) {
  const [d, setD] = useState(null)
  const load = useCallback(() => api('/api/admin/overview').then(setD).catch((e) => toast(e.message)), [toast])
  useEffect(() => { load() }, [load])
  if (!d) return <div className="spinner" />
  const cancel = async (id) => {
    const reason = await ask('Причина скасування матчу?')
    if (!reason) return
    await api('/api/admin/cancel', { room_id: id, reason }).catch((e) => toast(e.message))
    load()
  }
  return (
    <>
      <section className="card-box bank-card">
        <h3>🏦 Банк гри</h3>
        <div className="bank-sum">{d.bank.balance} <Chip /></div>
        <div className="terms">
          <div><span>Вільно для ставок ботів</span><b>{d.bank.available} <Chip /></b></div>
          <div><span>Зараз у резерві (йдуть матчі)</span><b>{d.bank.balance - d.bank.available} <Chip /></b></div>
        </div>
        <p className="hint">Поповнити: «Баланси» → отримувач «Банк гри», або в боті <code>/bank 10000 причина</code>.</p>
      </section>
      <section className="stats">
        <div><b>{d.fee}</b><span>комісія</span></div>
        <div><b>{d.users}</b><span>гравців</span></div>
        <div><b>{d.open_tickets}</b><span>звернень</span></div>
      </section>
      <section className="card-box">
        <h3>⭐ Telegram Stars</h3>
        <div className="terms">
          <div><span>Гравці заплатили (усього)</span><b>{d.stars.paid_total} ⭐</b></div>
          <div><span>Баланс Stars бота зараз</span><b>{d.stars.bot_balance ?? '—'} ⭐</b></div>
          <div><span>Повернень</span><b>{d.stars.refunds}</b></div>
          <div><span>Фішок витрачено в магазині</span><b>{d.shop}</b></div>
        </div>
        <p className="hint">{d.stars.withdraw_hint} Stars стають доступні для виведення через ~21 день після оплати.</p>
      </section>
      <section className="card-box">
        <h3>Активні кімнати ({d.active_rooms.length})</h3>
        <ul className="list">
          {d.active_rooms.map((r) => (
            <li key={r.id}>
              <div><b>{r.status === 'playing' ? '▶ гра' : '⏳ очікування'} · {r.mode === 'stake' ? `ставка ${r.stake}` : 'free'}</b>
                <small>{r.seats.join(', ')}</small><small>{r.match_id || r.id}</small></div>
              <button className="btn small warn" onClick={() => cancel(r.id)}>Скасувати</button>
            </li>
          ))}
        </ul>
        <p className="hint">Комісія зібрана: {d.fee}</p>
      </section>
    </>
  )
}

const WSTATUS = { pending: 'Очікує схвалення', approved: 'Схвалено · чекає виплати', completed: 'Виконано', rejected: 'Відхилено' }
function Withdrawals({ toast }) {
  const [list, setList] = useState([])
  const [filter, setFilter] = useState('open')
  const load = useCallback(() => {
    const status = filter
    api(`/api/admin/withdrawals${status ? `?status=${status}` : ''}`).then((r) => setList(r.requests)).catch((e) => toast(e.message))
  }, [filter, toast])
  useEffect(() => {
    load()
    const timer = setInterval(load, 30000)
    return () => clearInterval(timer)
  }, [load])
  const act = async (w, action, body = {}) => {
    try {
      await api(`/api/admin/withdrawals/${w.id}/${action}`, body)
      toast(`Заявку №${w.id} оновлено`)
      load()
    } catch (e) { toast(e.message) }
  }
  const reject = async (w) => {
    const reason = await ask('Причина відхилення заявки:')
    if (reason) await act(w, 'reject', { reason })
  }
  const complete = async (w) => {
    const payout_reference = await ask('Підтвердження ручної виплати (наприклад, нотатка про подарунок Stars):')
    if (payout_reference) await act(w, 'complete', { payout_reference })
  }
  return (
    <section className="card-box">
      <div className="seg wrap">
        {[['open', 'Відкриті'], ['pending', 'Очікують'], ['approved', 'Схвалені'], ['completed', 'Виконані'], ['rejected', 'Відхилені']].map(([id, name]) =>
          <button key={id} className={filter === id ? 'on' : ''} onClick={() => setFilter(id)}>{name}</button>)}
      </div>
      <ul className="list">
        {list.length === 0 && <li className="hint">Заявок немає</li>}
        {list.map((w) => (
          <li key={w.id}>
            <div><b>№{w.id} · {WSTATUS[w.status]}</b>
              <small>{w.name} · Telegram ID: {w.user_id}{w.username ? ` · @${w.username}` : ''}</small>
              <small>{ts(w.created_at)} · {w.chips} фішок → {w.stars} ⭐
                {w.eur_estimate != null ? ` · оцінка €${Number(w.eur_estimate).toFixed(2)}` : ''}</small>
              {w.decision_note && <small>Причина: {w.decision_note}</small>}
              {w.payout_reference && <small>Підтвердження виплати: {w.payout_reference}</small>}
            </div>
            <div className="right">
              {w.status === 'pending' && <>
                <button className="btn small primary" onClick={() => act(w, 'approve')}>Схвалити</button>
                <button className="btn small warn" onClick={() => reject(w)}>Відхилити</button>
              </>}
              {w.status === 'approved' && <>
                <button className="btn small primary" onClick={() => complete(w)}>Позначити виконаною</button>
                <button className="btn small warn" onClick={() => reject(w)}>Відхилити</button>
              </>}
            </div>
          </li>
        ))}
      </ul>
      <p className="hint">Після фактичного надсилання Stars позначте заявку виконаною та збережіть підтвердження.</p>
    </section>
  )
}

function Balances({ toast, reloadMe }) {
  const [q, setQ] = useState('')
  const [users, setUsers] = useState([])
  const [target, setTarget] = useState(null) // null = банк
  const [amount, setAmount] = useState('')
  const [reason, setReason] = useState('')
  const [tx, setTx] = useState([])
  const [bank, setBank] = useState(null)
  const loadBank = useCallback(() => api('/api/admin/overview').then((d) => setBank(d.bank)).catch(() => {}), [])
  useEffect(() => { loadBank() }, [loadBank])
  const search = useCallback(() => api(`/api/admin/users?q=${encodeURIComponent(q)}`).then((r) => setUsers(r.users)).catch((e) => toast(e.message)), [q, toast])
  useEffect(() => { search() }, []) // eslint-disable-line
  useEffect(() => {
    const acc = target ? `u:${target.id}` : 'bank'
    api(`/api/admin/transactions?account=${acc}`).then((r) => setTx(r.transactions)).catch(() => {})
  }, [target])
  const submit = async () => {
    try {
      const r = await api('/api/admin/adjust', { user_id: target ? target.id : null, amount: parseInt(amount, 10), reason })
      toast(`Готово. Новий баланс: ${r.balance}`)
      setAmount(''); setReason('')
      search(); reloadMe(); loadBank()
      setTarget(target ? { ...target } : null)
    } catch (e) { toast(e.message) }
  }
  const ban = async (u) => {
    const reason = await ask(u.banned ? 'Причина розблокування?' : 'Причина блокування?')
    if (!reason) return
    await api('/api/admin/ban', { user_id: u.id, banned: !u.banned, reason }).catch((e) => toast(e.message))
    search()
  }
  return (
    <>
      <section className="card-box">
        <h3>Нарахування / списання</h3>
        <p className="hint">Отримувач: <b>{target ? `${target.name} (${target.id})` : 'Банк гри (ставки ботів)'}</b>
          {!target && bank && <> · баланс <b>{bank.balance}</b> <Chip /> (вільно {bank.available})</>}
          {target && <button className="link" onClick={() => setTarget(null)}> → банк</button>}</p>
        <input type="number" placeholder="Сума (мінус = списання)" value={amount} onChange={(e) => setAmount(e.target.value)} />
        <input placeholder="Причина (обов'язково)" value={reason} onChange={(e) => setReason(e.target.value)} />
        <button className="btn primary" disabled={!amount || reason.trim().length < 3} onClick={submit}>Провести</button>
      </section>
      <section className="card-box">
        <div className="row"><input placeholder="ID, ім'я або @username" value={q} onChange={(e) => setQ(e.target.value)} />
          <button className="btn small" onClick={search}>Знайти</button></div>
        <ul className="list">
          {users.map((u) => (
            <li key={u.id} className={target?.id === u.id ? 'selected' : ''}>
              <div onClick={() => setTarget(u)}><b>{u.name}{u.banned ? ' 🚫' : ''}</b>
                <small>{u.id}{u.username ? ` · @${u.username}` : ''}</small></div>
              <div className="right"><b>{u.balance}</b>
                <button className="link" onClick={() => ban(u)}>{u.banned ? 'розбан' : 'бан'}</button></div>
            </li>
          ))}
        </ul>
      </section>
      <section className="card-box">
        <h3>Транзакції: {target ? target.name : 'банк'}</h3>
        <ul className="list">
          {tx.map((t) => (
            <li key={t.id}><div><b>{t.kind}</b><small>{ts(t.created_at)} {t.reason || ''} {t.ref || ''}</small></div>
              <b className={t.amount > 0 ? 'plus' : 'minus'}>{t.amount}</b></li>
          ))}
        </ul>
      </section>
    </>
  )
}

function Matches({ toast }) {
  const [q, setQ] = useState('')
  const [list, setList] = useState([])
  const [open, setOpen] = useState(null)
  const search = useCallback(() => api(`/api/admin/matches?q=${encodeURIComponent(q)}`).then((r) => setList(r.matches)).catch((e) => toast(e.message)), [q, toast])
  useEffect(() => { search() }, []) // eslint-disable-line
  const show = (id, reveal = false) => api(`/api/admin/match/${id}${reveal ? '?reveal=true' : ''}`).then(setOpen).catch((e) => toast(e.message))
  if (open) {
    const m = open.match
    const name = Object.fromEntries(m.players.map((p) => [p.pid, p.name]))
    return (
      <section className="card-box">
        <button className="link" onClick={() => setOpen(null)}>← назад</button>
        <h3>Матч {m.id}</h3>
        <p className="hint">{m.mode} · ставка {m.stake} · {m.status} · {m.rules.variant}</p>
        {m.result && <p>Результат: {m.result.draw ? 'нічия' : `дурень — ${name[m.result.loser] || '—'}`}</p>}
        {open.deal ? (
          <div className="deal">
            <h4>Роздача (розкрито, записано в аудит)</h4>
            {Object.entries(open.deal.hands).map(([pid, h]) => <p key={pid}><b>{name[pid]}:</b> {h.map(label).join(' ')}</p>)}
            <p><b>Козир:</b> {label(open.deal.trump_card)}</p>
          </div>
        ) : m.status !== 'playing' && (
          <button className="btn small" onClick={() => show(m.id, true)}>Розкрити роздачу (для спору)</button>
        )}
        {m.status === 'playing' && <p className="hint">Під час активного матчу карти гравців не розкриваються.</p>}
        <h4>Журнал подій</h4>
        <ol className="events">
          {open.events.map((e) => (
            <li key={e.seq}>
              <small>{new Date(e.ts * 1000).toLocaleTimeString('uk-UA')}</small>{' '}
              <b>{name[e.actor] || e.actor || 'система'}</b>{' '}
              {e.type === 'move' ? `${e.data.type}${e.data.card ? ' ' + label(e.data.card) : ''}${e.data.bout_end ? ` → ${e.data.bout_end === 'take' ? 'взяв' : 'бито'}` : ''}${e.data.bot ? ' 🤖' : ''}` : e.type}
            </li>
          ))}
        </ol>
      </section>
    )
  }
  return (
    <section className="card-box">
      <div className="row"><input placeholder="Номер матчу" value={q} onChange={(e) => setQ(e.target.value)} />
        <button className="btn small" onClick={search}>Знайти</button></div>
      <ul className="list">
        {list.map((m) => (
          <li key={m.id} onClick={() => show(m.id)}>
            <div><b>{m.id}</b><small>{ts(m.created_at)} · {m.mode}{m.stake ? ` ${m.stake}` : ''} · {m.status}</small>
              <small>{m.players.map((p) => p.name).join(', ')}</small></div>
          </li>
        ))}
      </ul>
    </section>
  )
}

function Tickets({ toast }) {
  const [list, setList] = useState([])
  const load = useCallback(() => api('/api/admin/tickets').then((r) => setList(r.tickets)).catch((e) => toast(e.message)), [toast])
  useEffect(() => { load() }, [load])
  const answer = async (t) => {
    const a = await ask('Відповідь гравцю:')
    if (!a) return
    await api('/api/admin/tickets/answer', { ticket_id: t.id, answer: a }).catch((e) => toast(e.message))
    load()
  }
  return (
    <section className="card-box">
      <ul className="list">
        {list.length === 0 && <li className="hint">Звернень немає</li>}
        {list.map((t) => (
          <li key={t.id}>
            <div><b>№{t.id} · {t.status === 'open' ? '🟡 відкрите' : '✅ закрите'}</b>
              <small>від {t.user_id} · {ts(t.created_at)}{t.match_id ? ` · матч ${t.match_id}` : ''}</small>
              <p>{t.text}</p>{t.answer && <small>Відповідь: {t.answer}</small>}</div>
            {t.status === 'open' && <button className="btn small" onClick={() => answer(t)}>Відповісти</button>}
          </li>
        ))}
      </ul>
    </section>
  )
}

function Modes({ toast, reloadMe }) {
  const [m, setM] = useState(null)
  useEffect(() => { api('/api/admin/overview').then((d) => setM({ ...d.modes, stakesText: d.modes.stakes.join(',') })).catch((e) => toast(e.message)) }, [toast])
  if (!m) return <div className="spinner" />
  const save = async () => {
    try {
      const body = {
        free: m.free, stake: m.stake, bots: m.bots,
        stakes: m.stakesText.split(',').map((x) => parseInt(x, 10)).filter((x) => x > 0),
        commission_percent: parseFloat(m.commission_percent) || 0,
        free_games_per_day: parseInt(m.free_games_per_day, 10) || 0,
        bot_fill_seconds: parseInt(m.bot_fill_seconds, 10) || 0,
        bot_level: m.bot_level,
      }
      await api('/api/admin/modes', body)
      toast('Збережено'); reloadMe()
    } catch (e) { toast(e.message) }
  }
  const set = (k) => (e) => setM({ ...m, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })
  return (
    <section className="card-box">
      <label className="toggle"><input type="checkbox" checked={m.free} onChange={set('free')} /> Безкоштовний режим</label>
      <label className="toggle"><input type="checkbox" checked={m.stake} onChange={set('stake')} /> Гра на фішки</label>
      <label className="toggle"><input type="checkbox" checked={m.bots} onChange={set('bots')} /> Боти</label>
      <h4>Ставки (через кому)</h4><input value={m.stakesText} onChange={set('stakesText')} />
      <h4>Комісія, %</h4><input type="number" value={m.commission_percent} onChange={set('commission_percent')} />
      <h4>Безкоштовних ігор на день (0 = без обмежень)</h4><input type="number" value={m.free_games_per_day} onChange={set('free_games_per_day')} />
      <h4>Через скільки секунд «Знайти гру» підсаджує ботів</h4><input type="number" value={m.bot_fill_seconds} onChange={set('bot_fill_seconds')} />
      <h4>Рівень ботів у швидкій грі</h4>
      <div className="seg">
        {[['mixed', 'Мікс'], ['easy', 'Легкі'], ['medium', 'Середні'], ['hard', 'Сильні']].map(([v, l]) => (
          <button key={v} className={m.bot_level === v ? 'on' : ''} onClick={() => setM({ ...m, bot_level: v })}>{l}</button>))}
      </div>
      <button className="btn primary" onClick={save}>Зберегти</button>
    </section>
  )
}

function Audit({ toast }) {
  const [list, setList] = useState([])
  useEffect(() => { api('/api/admin/audit').then((r) => setList(r.audit)).catch((e) => toast(e.message)) }, [toast])
  return (
    <section className="card-box">
      <ul className="list">
        {list.map((a) => (
          <li key={a.id}><div><b>{a.action}</b><small>{ts(a.ts)} · адмін {a.admin_id} · {a.target || ''}</small>
            <small>{a.data}</small></div></li>
        ))}
      </ul>
    </section>
  )
}
