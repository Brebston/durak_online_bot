import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import { lang, LANGS, setLang, t } from '../i18n.js'

const OUT = { win: [t('Перемога'), 'plus'], loss: [t('Дурень'), 'minus'], draw: [t('Нічия'), ''], cancelled: [t('Скасовано'), ''], playing: [t('Триває'), ''] }
const KIND = {
  deposit: t('Поповнення Stars'), admin_credit: t('Нарахування'), admin_debit: t('Списання'), stake_win: t('Виграш'),
  stake_loss: t('Програш'), refund: t('Повернення Stars'), withdrawal: t('Ручне виведення Stars'),
  player_transfer: t('Переказ фішок'),
}

export default function Profile({ me, reload, toast }) {
  const [hist, setHist] = useState(null)
  const [view, setView] = useState('matches')
  const [ticket, setTicket] = useState('')
  useEffect(() => { api('/api/history').then(setHist).catch((e) => toast(e.message)) }, [toast])
  const st = me.stats
  const rate = st.played ? Math.round((st.wins / st.played) * 100) : 0

  const save = async (patch) => {
    await api('/api/settings', { ...me.settings, ...patch }).catch((e) => toast(e.message))
    reload()
  }
  const sendTicket = async () => {
    try {
      const r = await api('/api/support', { text: ticket })
      setTicket('')
      toast(t('Звернення №{0} надіслано', r.id))
    } catch (e) { toast(e.message) }
  }

  return (
    <div className="profile">
      <section className="card-box">
        <h3>{me.name}</h3>
        <div className="level-box">
          <div className="level-num">{me.progress.level}</div>
          <div style={{ flex: 1 }}>
            <small className="hint">{t('Рівень') + ' '}{me.progress.level} · {me.progress.level_xp} / {me.progress.next_xp} XP</small>
            <div className="xpbar"><i style={{ width: `${Math.min(100, (me.progress.level_xp / me.progress.next_xp) * 100)}%` }} /></div>
          </div>
        </div>
        <p className="hint">Telegram ID: {me.id}{me.username ? ` · @${me.username}` : ''}</p>
        <div className="terms">
          <div><span>{t('Фішки')}</span><b>{me.balance.chips}</b></div>
          <div><span>{t('Доступно (без резервів)')}</span><b>{me.available.chips}</b></div>
          <div><span>{t('Статус перевірки')}</span><b>{t('не потрібна')}</b></div>
        </div>
      </section>

      <section className="stats">
        <div><b>{st.played}</b><span>{t('ігор')}</span></div>
        <div><b className="plus">{st.wins}</b><span>{t('перемог')}</span></div>
        <div><b className="minus">{st.losses}</b><span>{t('поразок')}</span></div>
        <div><b>{rate}%</b><span>{t('вінрейт')}</span></div>
      </section>

      <section className="card-box">
        <div className="seg">
          <button className={view === 'matches' ? 'on' : ''} onClick={() => setView('matches')}>{t('Матчі')}</button>
          <button className={view === 'tx' ? 'on' : ''} onClick={() => setView('tx')}>{t('Транзакції')}</button>
        </div>
        {!hist && <div className="spinner" />}
        {hist && view === 'matches' && (
          <ul className="list">
            {hist.matches.length === 0 && <li className="hint">{t('Ще немає матчів')}</li>}
            {hist.matches.map((m) => (
              <li key={m.id}>
                <div>
                  <b className={OUT[m.outcome][1]}>{OUT[m.outcome][0]}</b>
                  <small>{m.variant === 'perevodnoy' ? t('Перевідний') : t('Підкидний')} · vs {m.opponents.join(', ')}</small>
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
            {hist.transactions.length === 0 && <li className="hint">{t('Ще немає транзакцій')}</li>}
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
        <h3>{t('Налаштування')}</h3>
        <h4>🌐 Мова / Language</h4>
        <div className="seg wrap">
          {LANGS.map(([code, name]) => (
            <button key={code} className={lang === code ? 'on' : ''} onClick={() => code !== lang && setLang(code)}>{name}</button>
          ))}
        </div>
        <label className="toggle"><input type="checkbox" checked={me.settings.sound} onChange={(e) => save({ sound: e.target.checked })} />{' ' + t('Звук')}</label>
        <label className="toggle"><input type="checkbox" checked={me.settings.notify} onChange={(e) => save({ notify: e.target.checked })} />{' ' + t('Сповіщення')}</label>
        <label className="toggle"><input type="checkbox" checked={me.settings.discoverable} onChange={(e) => save({ discoverable: e.target.checked })} />{' ' + t('Мене можна знайти в пошуку гравців')}</label>
      </section>

      <section className="card-box">
        <details>
          <summary>{t('Правила гри')}</summary>
          <p><b>{t('Підкидний.')}</b>{' ' + t(
            'Колода 36 або 52 карти, по 6 на руки. Козир — нижня карта колоди. Перший ходить той, у кого наймолодший козир. Відбиватися можна старшою картою тієї ж масті або будь-яким козирем (некозирну карту). Підкидати можна карти тих рангів, що вже є на столі; у першому відбої — до 5 карт, далі до 6, але не більше, ніж карт у захисника. Не відбився — бере всі карти й пропускає хід. Після відбою всі добирають до 6: спершу атакувальник, захисник останнім.'
          )}</p>
          <p><b>{t('Перевідний.')}</b>{' ' + t(
            'Поки захисник не побив жодної карти, він може покласти карту того ж рангу й перевести атаку на наступного гравця, якщо в того вистачає карт.'
          )}</p>
          <p><b>{t('Кінець гри.')}</b>{' ' + t(
            'Коли колода скінчилась, гравці, що позбулися карт, виходять. Останній з картами — «дурень». Якщо останні гравці позбулися карт одночасно — нічия. Тричі пропущений хід = поразка.'
          )}</p>
        </details>
        <details>
          <summary>{t('Умови оплати')}</summary>
          <p>{t('Фішки купуються за Telegram Stars (1 ⭐ =') + ' '}{me.shop.rate}{' ' + t(
            'фішок). Фішки є балансом гри. Подати заявку на ручну виплату в Stars можна у вкладці «Вивід»; виплата потребує схвалення адміністратора і виконується вручну. Ставка резервується до старту. «Дурень» віддає ставку, решта ділять її порівну, комісія'
          ) + ' '}{me.modes.commission_percent}{t(
            '%. Нічия чи скасований матч — резерв повертається. Повернення Stars за невикористані фішки — через /paysupport у боті.'
          )}</p>
        </details>
        <details>
          <summary>{t('Підтримка')}</summary>
          <textarea value={ticket} onChange={(e) => setTicket(e.target.value)} placeholder={t('Опишіть проблему (можна вказати № матчу)')} />
          <button className="btn" onClick={sendTicket} disabled={ticket.trim().length < 5}>{t('Надіслати')}</button>
        </details>
      </section>
    </div>
  );
}
