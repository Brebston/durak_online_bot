import React, { useCallback, useEffect, useState } from 'react'
import { api, label } from '../api.js'
import { Avatar, Chip } from '../Fx.jsx'
import { t } from '../i18n.js'

const SECTIONS = [['overview', t('Огляд')], ['balance', t('Баланси')], ['withdrawals', t('Виведення')], ['matches', t('Матчі')], ['tickets', t('Звернення')], ['modes', t('Режими')], ['audit', t('Аудит')]]
const ts = (sec) => new Date(sec * 1000).toLocaleString('uk-UA')

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
          <button className="btn" onClick={() => done(null)}>{t('Скасувати')}</button>
        </div>
      </div></div>
  );
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
    const reason = await ask(t('Причина скасування матчу?'))
    if (!reason) return
    await api('/api/admin/cancel', { room_id: id, reason }).catch((e) => toast(e.message))
    load()
  }
  return (
    <>
      <section className="card-box bank-card">
        <h3>{t('🏦 Банк гри')}</h3>
        <div className="bank-sum">{d.bank.balance} <Chip /></div>
        <div className="terms">
          <div><span>{t('Вільно для ставок ботів')}</span><b>{d.bank.available} <Chip /></b></div>
          <div><span>{t('Зараз у резерві (йдуть матчі)')}</span><b>{d.bank.balance - d.bank.available} <Chip /></b></div>
        </div>
        <p className="hint">{t('Поповнити: «Баланси» → отримувач «Банк гри», або в боті') + ' '}<code>{t('/bank 10000 причина')}</code>.</p>
      </section>
      <section className="stats">
        <div><b>{d.fee}</b><span>{t('комісія')}</span></div>
        <div><b>{d.users}</b><span>{t('гравців')}</span></div>
        <div><b>{d.open_tickets}</b><span>{t('звернень')}</span></div>
      </section>
      <section className="card-box">
        <h3>⭐ Telegram Stars</h3>
        <div className="terms">
          <div><span>{t('Гравці заплатили (усього)')}</span><b>{d.stars.paid_total} ⭐</b></div>
          <div><span>{t('Баланс Stars бота зараз')}</span><b>{d.stars.bot_balance ?? '—'} ⭐</b></div>
          <div><span>{t('Повернень')}</span><b>{d.stars.refunds}</b></div>
          <div><span>{t('Фішок витрачено в магазині')}</span><b>{d.shop}</b></div>
        </div>
        <p className="hint">{d.stars.withdraw_hint}{' ' + t('Stars стають доступні для виведення через ~21 день після оплати.')}</p>
      </section>
      <section className="card-box">
        <h3>{t('Активні кімнати (')}{d.active_rooms.length})</h3>
        <ul className="list">
          {d.active_rooms.map((r) => (
            <li key={r.id}>
              <div><b>{r.status === 'playing' ? t('▶ гра') : t('⏳ очікування')} · {r.mode === 'stake' ? t('ставка {0}', r.stake) : 'free'}</b>
                <small>{r.seats.join(', ')}</small><small>{r.match_id || r.id}</small></div>
              <button className="btn small warn" onClick={() => cancel(r.id)}>{t('Скасувати')}</button>
            </li>
          ))}
        </ul>
        <p className="hint">{t('Комісія зібрана:') + ' '}{d.fee}</p>
      </section>
    </>
  );
}

const WSTATUS = { pending: t('Очікує схвалення'), approved: t('Схвалено · чекає виплати'), completed: t('Виконано'), rejected: t('Відхилено') }
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
      toast(t('Заявку №{0} оновлено', w.id))
      load()
    } catch (e) { toast(e.message) }
  }
  const reject = async (w) => {
    const reason = await ask(t('Причина відхилення заявки:'))
    if (reason) await act(w, 'reject', { reason })
  }
  const complete = async (w) => {
    const payout_reference = await ask(t('Підтвердження ручної виплати (наприклад, нотатка про подарунок Stars):'))
    if (payout_reference) await act(w, 'complete', { payout_reference })
  }
  return (
    <section className="card-box">
      <div className="seg wrap">
        {[['open', t('Відкриті')], ['pending', t('Очікують')], ['approved', t('Схвалені')], ['completed', t('Виконані')], ['rejected', t('Відхилені')]].map(([id, name]) =>
          <button key={id} className={filter === id ? 'on' : ''} onClick={() => setFilter(id)}>{name}</button>)}
      </div>
      <ul className="list">
        {list.length === 0 && <li className="hint">{t('Заявок немає')}</li>}
        {list.map((w) => (
          <li key={w.id}>
            <div><b>№{w.id} · {WSTATUS[w.status]}</b>
              <small>{w.name} · Telegram ID: {w.user_id}{w.username ? ` · @${w.username}` : ''}</small>
              <small>{ts(w.created_at)} · {w.chips}{' ' + t('фішок →') + ' '}{w.stars} ⭐
                {w.eur_estimate != null ? t(' · оцінка €{0}', Number(w.eur_estimate).toFixed(2)) : ''}</small>
              {w.decision_note && <small>{t('Причина:') + ' '}{w.decision_note}</small>}
              {w.payout_reference && <small>{t('Підтвердження виплати:') + ' '}{w.payout_reference}</small>}
            </div>
            <div className="right">
              {w.status === 'pending' && <>
                <button className="btn small primary" onClick={() => act(w, 'approve')}>{t('Схвалити')}</button>
                <button className="btn small warn" onClick={() => reject(w)}>{t('Відхилити')}</button>
              </>}
              {w.status === 'approved' && <>
                <button className="btn small primary" onClick={() => complete(w)}>{t('Позначити виконаною')}</button>
                <button className="btn small warn" onClick={() => reject(w)}>{t('Відхилити')}</button>
              </>}
            </div>
          </li>
        ))}
      </ul>
      <p className="hint">{t(
        'Після фактичного надсилання Stars позначте заявку виконаною та збережіть підтвердження.'
      )}</p>
    </section>
  );
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
      toast(t('Готово. Новий баланс: {0}', r.balance))
      setAmount(''); setReason('')
      search(); reloadMe(); loadBank()
      setTarget(target ? { ...target } : null)
    } catch (e) { toast(e.message) }
  }
  const removeAvatar = async (u) => {
    const reason = await ask(t('Причина видалення аватарки?'))
    if (!reason) return
    await api('/api/admin/avatar/remove', { user_id: u.id, reason }).catch((e) => toast(e.message))
    search()
  }
  const ban = async (u) => {
    const reason = await ask(u.banned ? t('Причина розблокування?') : t('Причина блокування?'))
    if (!reason) return
    await api('/api/admin/ban', { user_id: u.id, banned: !u.banned, reason }).catch((e) => toast(e.message))
    search()
  }
  return (
    <>
      <section className="card-box">
        <h3>{t('Нарахування / списання')}</h3>
        <p className="hint">{t('Отримувач:') + ' '}<b>{target ? `${target.name} (${target.id})` : t('Банк гри (ставки ботів)')}</b>
          {!target && bank && <>{' ' + t('· баланс') + ' '}<b>{bank.balance}</b> <Chip />{' ' + t('(вільно') + ' '}{bank.available})</>}
          {target && <button className="link" onClick={() => setTarget(null)}>{' ' + t('→ банк')}</button>}</p>
        <input type="number" placeholder={t('Сума (мінус = списання)')} value={amount} onChange={(e) => setAmount(e.target.value)} />
        <input placeholder={t('Причина (обов\'язково)')} value={reason} onChange={(e) => setReason(e.target.value)} />
        <button className="btn primary" disabled={!amount || reason.trim().length < 3} onClick={submit}>{t('Провести')}</button>
      </section>
      <section className="card-box">
        <div className="row"><input placeholder={t('ID, ім\'я або @username')} value={q} onChange={(e) => setQ(e.target.value)} />
          <button className="btn small" onClick={search}>{t('Знайти')}</button></div>
        <ul className="list">
          {users.map((u) => (
            <li key={u.id} className={target?.id === u.id ? 'selected' : ''}>
              <Avatar url={u.avatar_url} name={u.name} />
              <div className="grow" onClick={() => setTarget(u)}><b>{u.name}{u.banned ? ' 🚫' : ''}</b>
                <small>{u.id}{u.username ? ` · @${u.username}` : ''}</small></div>
              <div className="right"><b>{u.balance}</b>
                <button className="link" onClick={() => ban(u)}>{u.banned ? t('розбан') : t('бан')}</button>
                {u.avatar_url && <button className="link" onClick={() => removeAvatar(u)}>{t('прибрати фото')}</button>}</div>
            </li>
          ))}
        </ul>
      </section>
      <section className="card-box">
        <h3>{t('Транзакції:') + ' '}{target ? target.name : t('банк')}</h3>
        <ul className="list">
          {tx.map((row) => (
            <li key={row.id}><div><b>{row.kind}</b><small>{ts(row.created_at)} {row.reason || ''} {row.ref || ''}</small></div>
              <b className={row.amount > 0 ? 'plus' : 'minus'}>{row.amount}</b></li>
          ))}
        </ul>
      </section>
    </>
  );
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
        <button className="link" onClick={() => setOpen(null)}>{t('← назад')}</button>
        <h3>{t('Матч') + ' '}{m.id}</h3>
        <p className="hint">{m.mode}{' ' + t('· ставка') + ' '}{m.stake} · {m.status} · {m.rules.variant}</p>
        {m.result && <p>{t('Результат:') + ' '}{m.result.draw ? t('нічия') : t('дурень — {0}', name[m.result.loser] || '—')}</p>}
        {open.deal ? (
          <div className="deal">
            <h4>{t('Роздача (розкрито, записано в аудит)')}</h4>
            {Object.entries(open.deal.hands).map(([pid, h]) => <p key={pid}><b>{name[pid]}:</b> {h.map(label).join(' ')}</p>)}
            <p><b>{t('Козир:')}</b> {label(open.deal.trump_card)}</p>
          </div>
        ) : m.status !== 'playing' && (
          <button className="btn small" onClick={() => show(m.id, true)}>{t('Розкрити роздачу (для спору)')}</button>
        )}
        {m.status === 'playing' && <p className="hint">{t('Під час активного матчу карти гравців не розкриваються.')}</p>}
        <h4>{t('Журнал подій')}</h4>
        <ol className="events">
          {open.events.map((e) => (
            <li key={e.seq}>
              <small>{new Date(e.ts * 1000).toLocaleTimeString('uk-UA')}</small>{' '}
              <b>{name[e.actor] || e.actor || t('система')}</b>{' '}
              {e.type === 'move' ? `${e.data.type}${e.data.card ? ' ' + label(e.data.card) : ''}${e.data.bout_end ? ` → ${e.data.bout_end === 'take' ? t('взяв') : t('бито')}` : ''}${e.data.bot ? ' ' : ''}` : e.type}
            </li>
          ))}
        </ol>
      </section>
    );
  }
  return (
    <section className="card-box">
      <div className="row"><input placeholder={t('Номер матчу')} value={q} onChange={(e) => setQ(e.target.value)} />
        <button className="btn small" onClick={search}>{t('Знайти')}</button></div>
      <ul className="list">
        {list.map((m) => (
          <li key={m.id} onClick={() => show(m.id)}>
            <div><b>{m.id}</b><small>{ts(m.created_at)} · {m.mode}{m.stake ? ` ${m.stake}` : ''} · {m.status}</small>
              <small>{m.players.map((p) => p.name).join(', ')}</small></div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Tickets({ toast }) {
  const [list, setList] = useState([])
  const load = useCallback(() => api('/api/admin/tickets').then((r) => setList(r.tickets)).catch((e) => toast(e.message)), [toast])
  useEffect(() => { load() }, [load])
  const answer = async (tk) => {
    const a = await ask(t('Відповідь гравцю:'))
    if (!a) return
    await api('/api/admin/tickets/answer', { ticket_id: tk.id, answer: a }).catch((e) => toast(e.message))
    load()
  }
  return (
    <section className="card-box">
      <ul className="list">
        {list.length === 0 && <li className="hint">{t('Звернень немає')}</li>}
        {list.map((tk) => (
          <li key={tk.id}>
            <div><b>№{tk.id} · {tk.status === 'open' ? t('🟡 відкрите') : t('✅ закрите')}</b>
              <small>{t('від') + ' '}{tk.user_id} · {ts(tk.created_at)}{tk.match_id ? t(' · матч {0}', tk.match_id) : ''}</small>
              <p>{tk.text}</p>{tk.answer && <small>{t('Відповідь:') + ' '}{tk.answer}</small>}</div>
            {tk.status === 'open' && <button className="btn small" onClick={() => answer(tk)}>{t('Відповісти')}</button>}
          </li>
        ))}
      </ul>
    </section>
  );
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
      toast(t('Збережено')); reloadMe()
    } catch (e) { toast(e.message) }
  }
  const set = (k) => (e) => setM({ ...m, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })
  return (
    <section className="card-box">
      <label className="toggle"><input type="checkbox" checked={m.free} onChange={set('free')} />{' ' + t('Безкоштовний режим')}</label>
      <label className="toggle"><input type="checkbox" checked={m.stake} onChange={set('stake')} />{' ' + t('Гра на фішки')}</label>
      <label className="toggle"><input type="checkbox" checked={m.bots} onChange={set('bots')} />{' ' + t('Боти')}</label>
      <h4>{t('Ставки (через кому)')}</h4><input value={m.stakesText} onChange={set('stakesText')} />
      <h4>{t('Комісія, %')}</h4><input type="number" value={m.commission_percent} onChange={set('commission_percent')} />
      <h4>{t('Безкоштовних ігор на день (0 = без обмежень)')}</h4><input type="number" value={m.free_games_per_day} onChange={set('free_games_per_day')} />
      <h4>{t('Через скільки секунд «Знайти гру» підсаджує ботів')}</h4><input type="number" value={m.bot_fill_seconds} onChange={set('bot_fill_seconds')} />
      <h4>{t('Рівень ботів у швидкій грі')}</h4>
      <div className="seg">
        {[['mixed', t('Мікс')], ['easy', t('Легкі')], ['medium', t('Середні')], ['hard', t('Сильні')]].map(([v, l]) => (
          <button key={v} className={m.bot_level === v ? 'on' : ''} onClick={() => setM({ ...m, bot_level: v })}>{l}</button>))}
      </div>
      <button className="btn primary" onClick={save}>{t('Зберегти')}</button>
    </section>
  );
}

function Audit({ toast }) {
  const [list, setList] = useState([])
  useEffect(() => { api('/api/admin/audit').then((r) => setList(r.audit)).catch((e) => toast(e.message)) }, [toast])
  return (
    <section className="card-box">
      <ul className="list">
        {list.map((a) => (
          <li key={a.id}><div><b>{a.action}</b><small>{ts(a.ts)}{' ' + t('· адмін') + ' '}{a.admin_id} · {a.target || ''}</small>
            <small>{a.data}</small></div></li>
        ))}
      </ul>
    </section>
  );
}
