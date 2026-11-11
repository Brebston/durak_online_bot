import React, { useCallback, useEffect, useState } from 'react'
import { api } from '../api.js'

const OUT = { win: ['Перемога', 'plus'], loss: ['Дурень', 'minus'], draw: ['Нічия', ''], cancelled: ['Скасовано', ''], playing: ['Триває', ''] }
const KIND = {
  deposit: 'Поповнення Stars', admin_credit: 'Нарахування', admin_debit: 'Списання', stake_win: 'Виграш',
  stake_loss: 'Програш', refund: 'Повернення Stars', withdrawal: 'Ручне виведення Stars',
}
const WITHDRAWAL_STATUS = { pending: 'Очікує схвалення', approved: 'Схвалено · очікує виплати', completed: 'Виконано', rejected: 'Відхилено' }

export default function Profile({ me, reload, toast }) {
  const [hist, setHist] = useState(null)
  const [view, setView] = useState('matches')
  const [ticket, setTicket] = useState('')
  const [withdrawals, setWithdrawals] = useState([])
  const [withdrawChips, setWithdrawChips] = useState('')
  const [withdrawBusy, setWithdrawBusy] = useState(false)
  const loadWithdrawals = useCallback(() => api('/api/withdrawals').then((r) => setWithdrawals(r.requests)).catch((e) => toast(e.message)), [toast])
  useEffect(() => { api('/api/history').then(setHist).catch((e) => toast(e.message)) }, [toast])
  useEffect(() => {
    loadWithdrawals()
    const timer = setInterval(loadWithdrawals, 30000)
    return () => clearInterval(timer)
  }, [loadWithdrawals])
  const st = me.stats
  const rate = st.played ? Math.round((st.wins / st.played) * 100) : 0
  const chipsPerStar = me.withdrawal?.stars_per_chips || me.shop.rate
  const chipsValue = Number(withdrawChips)
  const hasOpenRequest = withdrawals.some((w) => ['pending', 'approved'].includes(w.status))
  const canRequest = Number.isInteger(chipsValue) && chipsValue > 0 && chipsValue % chipsPerStar === 0 &&
    chipsValue <= me.available.chips && !withdrawBusy && !hasOpenRequest

  const save = async (patch) => {
    await api('/api/settings', { ...me.settings, ...patch }).catch((e) => toast(e.message))
    reload()
  }
  const sendTicket = async () => {
    try {
      const r = await api('/api/support', { text: ticket })
      setTicket('')
      toast(`Звернення №${r.id} надіслано`)
    } catch (e) { toast(e.message) }
  }
  const requestWithdrawal = async () => {
    if (!canRequest) return
    setWithdrawBusy(true)
    try {
      const r = await api('/api/withdrawals', { chips: chipsValue })
      toast(`Заявку №${r.id} на ${r.stars} ⭐ створено`)
      setWithdrawChips('')
      await Promise.all([loadWithdrawals(), reload()])
    } catch (e) { toast(e.message) } finally { setWithdrawBusy(false) }
  }

  return (
    <div className="profile">
      <section className="card-box">
        <h3>{me.name}</h3>
        <p className="hint">Telegram ID: {me.id}{me.username ? ` · @${me.username}` : ''}</p>
        <div className="terms">
          <div><span>Фішки</span><b>{me.balance.chips}</b></div>
          <div><span>Доступно (без резервів)</span><b>{me.available.chips}</b></div>
          <div><span>Статус перевірки</span><b>не потрібна</b></div>
        </div>
      </section>

      <section className="stats">
        <div><b>{st.played}</b><span>ігор</span></div>
        <div><b className="plus">{st.wins}</b><span>перемог</span></div>
        <div><b className="minus">{st.losses}</b><span>поразок</span></div>
        <div><b>{rate}%</b><span>вінрейт</span></div>
      </section>

      <section className="card-box">
        <h3>Ручне виведення в Telegram Stars</h3>
        <p className="hint">Заявка резервує фішки. Після схвалення адміністратор надішле Stars вручну; це може зайняти час.
          Кількість Stars рахується за курсом 1 ⭐ = {chipsPerStar} фішок.</p>
        <input type="number" min={chipsPerStar} step={chipsPerStar} max={me.available.chips}
          placeholder={`Сума фішок (кратно ${chipsPerStar})`} value={withdrawChips}
          onChange={(e) => setWithdrawChips(e.target.value)} />
        {Number.isInteger(chipsValue) && chipsValue > 0 && chipsValue % chipsPerStar === 0 && (
          <p className="hint">До виплати: <b>{chipsValue / chipsPerStar} ⭐</b>
            {me.withdrawal?.eur_per_star ? ` · орієнтовно €${(chipsValue / chipsPerStar * me.withdrawal.eur_per_star).toFixed(2)}` : ''}</p>
        )}
        <button className="btn primary" disabled={!canRequest} onClick={requestWithdrawal}>
          {withdrawBusy ? 'Надсилання…' : 'Подати заявку'}
        </button>
        {hasOpenRequest && <p className="hint">У вас уже є відкрита заявка. Нову можна подати після її закриття.</p>}
        <h4>Мої заявки</h4>
        <ul className="list">
          {withdrawals.length === 0 && <li className="hint">Заявок ще немає</li>}
          {withdrawals.map((w) => (
            <li key={w.id}><div><b>№{w.id} · {WITHDRAWAL_STATUS[w.status]}</b>
              <small>{new Date(w.created_at * 1000).toLocaleString('uk-UA')} · {w.chips} фішок → {w.stars} ⭐
                {w.eur_estimate != null ? ` · орієнтовно €${Number(w.eur_estimate).toFixed(2)}` : ''}</small>
              {w.decision_note && <small>Причина: {w.decision_note}</small>}
            </div></li>
          ))}
        </ul>
      </section>

      <section className="card-box">
        <div className="seg">
          <button className={view === 'matches' ? 'on' : ''} onClick={() => setView('matches')}>Матчі</button>
          <button className={view === 'tx' ? 'on' : ''} onClick={() => setView('tx')}>Транзакції</button>
        </div>
        {!hist && <div className="spinner" />}
        {hist && view === 'matches' && (
          <ul className="list">
            {hist.matches.length === 0 && <li className="hint">Ще немає матчів</li>}
            {hist.matches.map((m) => (
              <li key={m.id}>
                <div>
                  <b className={OUT[m.outcome][1]}>{OUT[m.outcome][0]}</b>
                  <small>{m.variant === 'perevodnoy' ? 'Перевідний' : 'Підкидний'} · vs {m.opponents.join(', ')}</small>
                  <small>{new Date(m.created_at * 1000).toLocaleString('uk-UA')} · №{m.id}</small>
                </div>
                <b className={m.delta > 0 ? 'plus' : m.delta < 0 ? 'minus' : ''}>
                  {m.mode === 'stake' ? `${m.delta > 0 ? '+' : ''}${m.delta}` : 'free'}
                </b>
              </li>
            ))}
          </ul>
        )}
        {hist && view === 'tx' && (
          <ul className="list">
            {hist.transactions.length === 0 && <li className="hint">Ще немає транзакцій</li>}
            {hist.transactions.map((t) => (
              <li key={t.id}>
                <div>
                  <b>{KIND[t.kind] || t.kind}</b>
                  <small>{new Date(t.created_at * 1000).toLocaleString('uk-UA')}{t.reason ? ` · ${t.reason}` : ''}</small>
                </div>
                <b className={t.amount > 0 ? 'plus' : 'minus'}>{t.amount > 0 ? '+' : ''}{t.amount}</b>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="card-box">
        <h3>Налаштування</h3>
        <label className="toggle"><input type="checkbox" checked={me.settings.sound} onChange={(e) => save({ sound: e.target.checked })} /> Звук</label>
        <label className="toggle"><input type="checkbox" checked={me.settings.notify} onChange={(e) => save({ notify: e.target.checked })} /> Сповіщення</label>
        <label className="toggle"><input type="checkbox" checked={me.settings.discoverable} onChange={(e) => save({ discoverable: e.target.checked })} /> Мене можна знайти в пошуку гравців</label>
      </section>

      <section className="card-box">
        <details>
          <summary>Правила гри</summary>
          <p><b>Підкидний.</b> Колода 36 або 52 карти, по 6 на руки. Козир — нижня карта колоди. Перший ходить той, у кого
            наймолодший козир. Відбиватися можна старшою картою тієї ж масті або будь-яким козирем (некозирну карту).
            Підкидати можна карти тих рангів, що вже є на столі; у першому відбої — до 5 карт, далі до 6, але не більше,
            ніж карт у захисника. Не відбився — бере всі карти й пропускає хід. Після відбою всі добирають до 6:
            спершу атакувальник, захисник останнім.</p>
          <p><b>Перевідний.</b> Поки захисник не побив жодної карти, він може покласти карту того ж рангу й перевести
            атаку на наступного гравця, якщо в того вистачає карт.</p>
          <p><b>Кінець гри.</b> Коли колода скінчилась, гравці, що позбулися карт, виходять. Останній з картами — «дурень».
            Якщо останні гравці позбулися карт одночасно — нічия. Тричі пропущений хід = поразка.</p>
        </details>
        <details>
          <summary>Умови оплати</summary>
          <p>Фішки купуються за Telegram Stars (1 ⭐ = {me.shop.rate} фішок). Фішки є балансом гри. Для них можна подати
            заявку на ручну виплату в Stars за курсом 1 ⭐ = {chipsPerStar} фішок; виплата потребує схвалення адміністратора і виконується вручну.
            Ставка резервується до старту. «Дурень» віддає ставку, решта
            ділять її порівну, комісія {me.modes.commission_percent}%. Нічия чи скасований матч — резерв повертається.
            Повернення Stars за невикористані фішки — через /paysupport у боті.</p>
        </details>
        <details>
          <summary>Підтримка</summary>
          <textarea value={ticket} onChange={(e) => setTicket(e.target.value)} placeholder="Опишіть проблему (можна вказати № матчу)" />
          <button className="btn" onClick={sendTicket} disabled={ticket.trim().length < 5}>Надіслати</button>
        </details>
      </section>
    </div>
  )
}
