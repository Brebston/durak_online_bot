import React, { useCallback, useEffect, useState } from 'react'
import { api, label } from '../api.js'
import { Avatar, Chip } from '../Fx.jsx'
import { t } from '../i18n.js'

const SECTIONS = [['overview', t('Огляд')], ['analytics', t('Аналітика')], ['alerts', t('Сигнали')], ['broadcast', t('Розсилка')], ['balance', t('Баланси')], ['matches', t('Матчі')], ['tickets', t('Звернення')], ['modes', t('Режими')], ['audit', t('Аудит')]]
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
      {sec === 'analytics' && <Analytics toast={toast} />}
      {sec === 'alerts' && <Alerts toast={toast} />}
      {sec === 'broadcast' && <Broadcast toast={toast} />}
      {sec === 'balance' && <Balances toast={toast} reloadMe={reloadMe} />}
      {sec === 'matches' && <Matches toast={toast} />}
      {sec === 'tickets' && <Tickets toast={toast} />}
      {sec === 'modes' && <Modes toast={toast} reloadMe={reloadMe} />}
      {sec === 'audit' && <Audit toast={toast} />}
    </div>
  )
}

const PERIODS = [['today', t('Сьогодні')], ['7d', t('7 днів')], ['30d', t('30 днів')], ['all', t('Увесь час')]]

function BankReport({ toast }) {
  const [period, setPeriod] = useState('7d')
  const [r, setR] = useState(null)
  useEffect(() => {
    const tz = -new Date().getTimezoneOffset()
    api(`/api/admin/bank?period=${period}&tz=${tz}`).then(setR).catch((e) => toast(e.message))
  }, [period, toast])
  const sign = (n) => (n > 0 ? `+${n}` : `${n}`)
  return (
    <section className="card-box">
      <h3>{t('📈 Результати банку')}</h3>
      <div className="seg">
        {PERIODS.map(([v, l]) => <button key={v} className={period === v ? 'on' : ''} onClick={() => setPeriod(v)}>{l}</button>)}
      </div>
      {!r && <div className="spinner" />}
      {r && (
        <>
          <div className="stats bank-stats">
            <div><b className="plus">+{r.won}</b><span>{t('боти виграли')}</span></div>
            <div><b className="minus">−{r.lost}</b><span>{t('боти програли')}</span></div>
            <div><b className={r.game_net >= 0 ? 'plus' : 'minus'}>{sign(r.game_net)}</b><span>{t('підсумок ігор')}</span></div>
          </div>
          <div className="terms">
            <div><span>{t('Матчів виграно / програно')}</span><b>{r.matches_won} / {r.matches_lost}</b></div>
            <div><span>{t('Комісія з матчів')}</span><b className="plus">+{r.fee} <Chip /></b></div>
            <div><span>{t('Покупки в магазині')}</span><b className="plus">+{r.shop} <Chip /></b></div>
            <div><span>{t('Поповнення адміном')}</span><b>+{r.topups} <Chip /></b></div>
            <div><span>{t('Списано адміном')}</span><b>−{r.withdrawn} <Chip /></b></div>
            <div><span>{t('Зміна банку за період')}</span><b className={r.total >= 0 ? 'plus' : 'minus'}>{sign(r.total)} <Chip /></b></div>
          </div>
          {r.daily.length > 0 && (
            <>
              <h4>{t('По днях (останні 14)')}</h4>
              <table className="daily">
                <thead><tr><th>{t('Дата')}</th><th>{t('Ігри')}</th><th>{t('Комісія')}</th><th>{t('Магазин')}</th></tr></thead>
                <tbody>
                  {r.daily.map((row) => (
                    <tr key={row.d}>
                      <td>{row.d.slice(5)}</td>
                      <td className={row.game >= 0 ? 'plus' : 'minus'}>{sign(row.game)}</td>
                      <td>{row.fee}</td>
                      <td>{row.shop}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </>
      )}
    </section>
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
        <p className="hint">{t('У банк автоматично йдуть комісія з матчів і всі фішки, витрачені в магазині.')}</p>
      </section>
      <BankReport toast={toast} />
      <section className="stats">
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
      </section>
    </>
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
        ranked: m.ranked, tournaments: m.tournaments,
        tournament_wait: parseInt(m.tournament_wait, 10) || 180,
        room_fill_seconds: parseInt(m.room_fill_seconds, 10) || 45,
        alert_amount: parseInt(m.alert_amount, 10) || 0,
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
      <label className="toggle"><input type="checkbox" checked={m.ranked} onChange={set('ranked')} />{' ' + t('Рейтингові матчі')}</label>
      <label className="toggle"><input type="checkbox" checked={m.tournaments} onChange={set('tournaments')} />{' ' + t('Турніри')}</label>
      <h4>{t('Скільки секунд чекати гравців у турнірі після першої реєстрації')}</h4><input type="number" value={m.tournament_wait} onChange={set('tournament_wait')} />
      <h4>{t('Через скільки секунд вільні місця у власній кімнаті займають боти')}</h4><input type="number" value={m.room_fill_seconds} onChange={set('room_fill_seconds')} />
      <h4>{t('Сповіщати про операції від (фішок, 0 — ні)')}</h4><input type="number" value={m.alert_amount} onChange={set('alert_amount')} />
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

function Bars({ rows, field, fmt }) {
  const max = Math.max(1, ...rows.map((r) => r[field] || 0))
  return (
    <div className="bars">
      {rows.map((r) => (
        <div key={r.day} className="bar" title={`${r.day}: ${r[field] ?? '—'}`}>
          <i style={{ height: `${(100 * (r[field] || 0)) / max}%` }} />
          <small>{fmt ? fmt(r[field]) : r[field] ?? '—'}</small>
          <em>{r.day.slice(8)}</em>
        </div>
      ))}
    </div>
  )
}

const KIND_NAME = { quick: t('Швидка гра'), private: t('Кімната'), rematch: t('Реванш'), tournament: t('Турнір') }
const MODE_NAME = { free: t('Безкоштовно'), stake: t('На фішки'), ranked: t('Рейтингова') }

function Analytics({ toast }) {
  const [days, setDays] = useState(14)
  const [a, setA] = useState(null)
  useEffect(() => { setA(null); api(`/api/admin/analytics?days=${days}`).then(setA).catch((e) => toast(e.message)) }, [days, toast])
  if (!a) return <div className="spinner" />
  const today = a.series[a.series.length - 1]
  const total = a.modes.reduce((x, m) => x + m.n, 0) || 1
  return (
    <>
      <div className="seg">
        {[[7, t('7 днів')], [14, t('14 днів')], [30, t('30 днів')]].map(([v, l]) => <button key={v} className={days === v ? 'on' : ''} onClick={() => setDays(v)}>{l}</button>)}
      </div>
      <section className="stats">
        <div><b>{a.online}</b><span>{t('онлайн зараз')}</span></div>
        <div><b>{today.dau}</b><span>{t('DAU сьогодні')}</span></div>
        <div><b>{a.totals.wau}</b><span>{t('за 7 днів')}</span></div>
        <div><b>{a.totals.users}</b><span>{t('усього')}</span></div>
      </section>
      <section className="card-box"><h3>{t('Активні гравці за день (DAU)')}</h3><Bars rows={a.series} field="dau" /></section>
      <section className="card-box"><h3>{t('Нові гравці')}</h3><Bars rows={a.series} field="new" /></section>
      <section className="card-box">
        <h3>{t('Повернення наступного дня (D1), %')}</h3>
        <Bars rows={a.series} field="d1" fmt={(v) => (v === null || v === undefined ? '—' : `${v}`)} />
        <p className="hint">{t('Частка новачків дня, які зайшли ще раз наступного дня.')}</p>
      </section>
      <section className="card-box"><h3>{t('Матчів за день')}</h3><Bars rows={a.series} field="games" /></section>
      <section className="card-box"><h3>{t('Куплено фішок за Stars')}</h3><Bars rows={a.series} field="chips_bought" /></section>
      <section className="card-box">
        <h3>{t('Популярні режими')}</h3>
        <ul className="list">
          {a.modes.length === 0 && <li className="hint">{t('Ще немає матчів')}</li>}
          {a.modes.map((m, i) => (
            <li key={i}>
              <div>
                <b>{MODE_NAME[m.mode] || m.mode} · {KIND_NAME[m.kind] || m.kind}</b>
                <small>{m.variant === 'perevodnoy' ? t('Перевідний') : t('Підкидний')} · {m.size}{' ' + t('гравці')}</small>
              </div>
              <b>{m.n} · {Math.round((100 * m.n) / total)}%</b>
            </li>
          ))}
        </ul>
      </section>
    </>
  )
}

function Alerts({ toast }) {
  const [d, setD] = useState(null)
  const load = useCallback(() => api('/api/admin/alerts').then(setD).catch((e) => toast(e.message)), [toast])
  useEffect(() => { load() }, [load])
  if (!d) return <div className="spinner" />
  const seen = () => api('/api/admin/alerts/seen', {}).then(load).catch((e) => toast(e.message))
  return (
    <>
      <section className="card-box">
        <h3>{t('⚠️ Підозріле')}</h3>
        <p className="hint">{t('Великі операції, багато переказів одному гравцю, часті скарги. Нові сигнали також приходять адмінам у бот.')}</p>
        <ul className="list">
          {d.alerts.length === 0 && <li className="hint">{t('Поки все спокійно')}</li>}
          {d.alerts.map((a) => (
            <li key={a.id} className={a.seen ? '' : 'unseen'}><div><b>{t(a.text)}</b><small>{ts(a.created_at)}</small></div></li>
          ))}
        </ul>
        <button className="btn" onClick={seen}>{t('Позначити переглянутими')}</button>
      </section>
      <section className="card-box">
        <h3>{t('🚩 Скарги гравців')}</h3>
        <ul className="list">
          {d.reports.length === 0 && <li className="hint">{t('Скарг немає')}</li>}
          {d.reports.map((r) => (
            <li key={r.id} className={r.status === 'open' ? 'unseen' : ''}>
              <div>
                <b>{r.target_name || r.target_id} ({r.target_id})</b>
                <small>{t(r.reason)} · {t('від') + ' '}{r.from_name || r.from_id} · {ts(r.created_at)}{r.match_id ? ` · №${r.match_id}` : ''}</small>
              </div>
            </li>
          ))}
        </ul>
      </section>
    </>
  )
}

function Broadcast({ toast }) {
  const [text, setText] = useState('')
  const [button, setButton] = useState(t('🃏 Грати'))
  const [st, setSt] = useState(null)
  const [backup, setBackup] = useState(null)
  const [armed, setArmed] = useState(false)
  const load = useCallback(() => api('/api/admin/broadcast').then(setSt).catch((e) => toast(e.message)), [toast])
  useEffect(() => {
    load()
    api('/api/admin/alerts').then((d) => setBackup(d.last_backup)).catch(() => {})
    const timer = setInterval(load, 3000)
    return () => clearInterval(timer)
  }, [load])
  const go = async (test) => {
    if (!test && !armed) { setArmed(true); return }
    setArmed(false)
    try {
      await api('/api/admin/broadcast', { text, button, test })
      toast(test ? t('Тестове повідомлення надіслано вам у бот') : t('Розсилку запущено'))
      load()
    } catch (e) { toast(e.message) }
  }
  const doBackup = async () => {
    try {
      const r = await api('/api/admin/backup', {})
      toast(t('Бекап {0} КБ надіслано в бот', Math.round(r.size / 1024)))
      setBackup(Date.now() / 1000)
    } catch (e) { toast(e.message) }
  }
  return (
    <>
      <section className="card-box">
        <h3>{t('📣 Розсилка в боті')}</h3>
        <p className="hint">{t('Отримають лише ті, хто не вимкнув сповіщення:') + ' '}<b>{st?.recipients ?? '…'}</b></p>
        <textarea value={text} maxLength={3500} onChange={(e) => setText(e.target.value)} placeholder={t('Текст повідомлення')} />
        <h4>{t('Текст кнопки')}</h4>
        <input value={button} maxLength={40} onChange={(e) => setButton(e.target.value)} />
        <div className="actions-col">
          <button className="btn" disabled={!text.trim() || !st?.bot} onClick={() => go(true)}>{t('Надіслати тест собі')}</button>
          <button className="btn primary" disabled={!text.trim() || !st?.bot || st?.running} onClick={() => go(false)}>{armed ? t('Точно надіслати {0} гравцям?', st?.recipients) : t('Надіслати всім')}</button>
        </div>
        {st && !st.bot && <p className="hint warn">{t('Бот не запущений — розсилка недоступна.')}</p>}
        {st?.total !== undefined && (
          <p className="hint">{st.running ? t('Йде розсилка:') : t('Остання розсилка:')}{' '}{st.sent}/{st.total}{st.failed ? ` · ${t('не доставлено')} ${st.failed}` : ''}</p>
        )}
      </section>
      <section className="card-box">
        <h3>{t('💾 Бекап бази')}</h3>
        <p className="hint">{t('Щодня база автоматично надсилається адмінам у бот файлом .db.gz.') + ' '}{backup ? t('Останній: {0}', ts(backup)) : t('Ще не було')}</p>
        <button className="btn" onClick={doBackup}>{t('Зробити бекап зараз')}</button>
      </section>
    </>
  )
}
