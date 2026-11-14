import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import { lang, LANGS, setLang, t, titleText } from '../i18n.js'
import { Avatar } from '../Fx.jsx'
import { ACH_ICON } from './PlayerCard.jsx'

const OUT = { win: [t('Перемога'), 'plus'], loss: [t('Дурень'), 'minus'], draw: [t('Нічия'), ''], cancelled: [t('Скасовано'), ''], playing: [t('Триває'), ''] }
const KIND = {
  deposit: t('Поповнення Stars'), admin_credit: t('Нарахування'), admin_debit: t('Списання'), stake_win: t('Виграш'),
  stake_loss: t('Програш'), refund: t('Повернення Stars'), withdrawal: t('Ручне виведення Stars'),
  player_transfer: t('Переказ фішок'),
}

export default function Profile({ me, reload, toast, onReplay }) {
  const [hist, setHist] = useState(null)
  const [view, setView] = useState('matches')
  const [ticket, setTicket] = useState('')
  const [prog, setProg] = useState(null)
  useEffect(() => { api('/api/history').then(setHist).catch((e) => toast(e.message)) }, [toast])
  useEffect(() => { api('/api/progress').then(setProg).catch(() => {}) }, [me.progress.xp])
  const pickTitle = (id) => api('/api/title', { title_id: id }).then(() => { reload(); api('/api/progress').then(setProg) }).catch((e) => toast(e.message))
  const claimTier = async (tier) => {
    try {
      const r = await api('/api/season/claim', { tier })
      toast(r.title ? t('Отримано титул «{0}» і +{1} XP', r.title, r.xp) : t('Отримано +{0} XP', r.xp))
      setProg((p) => ({ ...p, pass: r.pass }))
      reload()
    } catch (e) { toast(e.message) }
  }
  const st = me.stats
  const rate = st.played ? Math.round((st.wins / st.played) * 100) : 0

  const save = async (patch) => {
    await api('/api/settings', { ...me.settings, ...patch }).catch((e) => toast(e.message))
    reload()
  }
  const setAvatar = async (kind, data) => {
    try {
      await api('/api/avatar', { kind, data })
      reload()
    } catch (e) { toast(e.message) }
  }
  // зменшуємо фото на пристрої (квадрат 256×256), сервер ще раз перекодує
  const uploadAvatar = (file) => {
    if (!file) return
    const img = new Image()
    img.onload = () => {
      const side = Math.min(img.width, img.height)
      const c = document.createElement('canvas')
      c.width = c.height = 256
      c.getContext('2d').drawImage(img, (img.width - side) / 2, (img.height - side) / 2, side, side, 0, 0, 256, 256)
      URL.revokeObjectURL(img.src)
      setAvatar('custom', c.toDataURL('image/jpeg', 0.85))
    }
    img.onerror = () => toast(t('Не вдалося прочитати зображення'))
    img.src = URL.createObjectURL(file)
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
        <div className="profile-head">
          <Avatar url={me.avatar?.url} name={me.name} size={72} />
          <div>
            <h3>{me.name}</h3>
            <div className="avatar-actions">
              <label className="btn small">{t('📷 Завантажити фото')}
                <input type="file" accept="image/*" hidden onChange={(e) => uploadAvatar(e.target.files?.[0])} />
              </label>
              {me.avatar?.has_tg && me.avatar.kind !== 'tg' && <button className="btn small" onClick={() => setAvatar('tg')}>{t('Фото з Telegram')}</button>}
              {me.avatar?.url && <button className="link" onClick={() => setAvatar('none')}>{t('Прибрати')}</button>}
            </div>
          </div>
        </div>
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

      {prog && (
        <section className="card-box progress-box">
          <div className="terms">
            <div><span>{t('📈 Рейтинг')}</span><b>{prog.rating.value}</b></div>
            <div><span>{t('🔥 Серія днів')}</span><b>{prog.streak.days} ({t('рекорд') + ' '}{prog.streak.best})</b></div>
          </div>
          {prog.titles.length > 0 && (
            <>
              <h4>{t('Титул')}</h4>
              <select value={prog.titles.find((x) => x.label === prog.title)?.title_id || ''} onChange={(e) => pickTitle(e.target.value)}>
                <option value="">{t('— без титулу —')}</option>
                {prog.titles.map((x) => <option key={x.title_id} value={x.title_id}>{titleText(x.label)}</option>)}
              </select>
            </>
          )}
          <h4>{t('Завдання на сьогодні')}</h4>
          <ul className="quests">
            {prog.quests.map((q) => (
              <li key={q.qid} className={q.done ? 'done' : ''}>
                <div>
                  <span>{q.done ? '✅ ' : ''}{t(q.text, q.target)}</span>
                  <div className="xpbar"><i style={{ width: `${(100 * q.progress) / q.target}%` }} /></div>
                </div>
                <small>{q.progress}/{q.target} · +{q.reward} XP</small>
              </li>
            ))}
          </ul>
          {prog.pass && (
            <>
              <h4>{t('🎟 Пропуск сезону {0}', prog.pass.season)} · {prog.pass.points} {t('очок')}</h4>
              <ul className="pass">
                {prog.pass.tiers.map((x) => (
                  <li key={x.tier} className={x.claimed ? 'done' : x.unlocked ? 'open' : ''}>
                    <div>
                      <b>{x.tier}</b>
                      <small>{x.points} {t('очок')} · +{x.xp} XP{x.title ? ' · ' + t('титул') : ''}</small>
                    </div>
                    {x.claimed ? <span className="hint">{t('✓ Отримано')}</span>
                      : x.unlocked ? <button className="btn small primary" onClick={() => claimTier(x.tier)}>{t('Забрати')}</button>
                        : <span className="lock">🔒</span>}
                  </li>
                ))}
              </ul>
            </>
          )}
          {prog.weekly?.length > 0 && (
            <>
              <h4>{t('Завдання тижня')}</h4>
              <ul className="quests">
                {prog.weekly.map((q) => (
                  <li key={q.qid} className={q.done ? 'done' : ''}>
                    <div>
                      <span>{q.done ? '✅ ' : ''}{t(q.text, q.target)}</span>
                      <div className="xpbar"><i style={{ width: `${(100 * q.progress) / q.target}%` }} /></div>
                    </div>
                    <small>{q.progress}/{q.target} · +{q.reward} XP</small>
                  </li>
                ))}
              </ul>
            </>
          )}
          <h4>{t('Досягнення')} · {prog.achievements.filter((a) => a.unlocked).length}/{prog.achievements.length}</h4>
          <div className="badges">
            {prog.achievements.map((a) => (
              <div key={a.id} className={`ach ${a.unlocked ? 'on' : ''}`} onClick={() => toast(`${t(a.name)} — ${t(a.desc)} (${a.progress}/${a.target})`)}>
                <span>{ACH_ICON[a.id] || '⭐'}</span>
                <small>{t(a.name)}</small>
              </div>
            ))}
          </div>
        </section>
      )}

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
                <div className="match-right">
                  <b className={m.delta > 0 ? 'plus' : m.delta < 0 ? 'minus' : ''}>
                    {m.mode === 'stake' ? `${m.delta > 0 ? '+' : ''}${m.delta}` : 'free'}
                  </b>
                  {m.outcome !== 'playing' && onReplay && (
                    <button className="btn small" title={t('Переглянути реплей')} onClick={() => onReplay(m.id)}>▶</button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
        {hist && view === 'tx' && (
          <ul className="list">
            {hist.transactions.length === 0 && <li className="hint">{t('Ще немає транзакцій')}</li>}
            {hist.transactions.map((tx) => (
              <li key={tx.id}>
                <div>
                  <b>{KIND[tx.kind] || tx.kind}</b>
                  <small>{new Date(tx.created_at * 1000).toLocaleString('uk-UA')}{tx.reason ? ` · ${tx.reason}` : ''}</small>
                </div>
                <b className={tx.amount > 0 ? 'plus' : 'minus'}>{tx.amount > 0 ? '+' : ''}{tx.amount}</b>
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
            'фішок). Фішки — ігрова валюта: на них грають, купують оформлення й можна подати заявку на ручне виведення в Telegram Stars. Виплату проводить адміністратор вручну після схвалення заявки. Ставка резервується до старту. «Дурень» віддає ставку, решта ділять її порівну, комісія'
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
