import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import { t } from '../i18n.js'

function Seg({ value, options, onChange }) {
  return (
    <div className="seg">
      {options.map(([v, l]) => (
        <button key={String(v)} className={value === v ? 'on' : ''} onClick={() => onChange(v)}>{l}</button>
      ))}
    </div>
  )
}

export default function Lobby({ me, send }) {
  const modes = me.modes
  const [mode, setMode] = useState(modes.free ? 'free' : 'stake')
  const [size, setSize] = useState(2)
  const [variant, setVariant] = useState('podkidnoy')
  const [deck, setDeck] = useState(36)
  const [stake, setStake] = useState(modes.stakes[0] || 10)
  const [turn, setTurn] = useState(30)
  const [cheating, setCheating] = useState(false)
  const [view, setView] = useState('quick') // quick | rooms
  const [rooms, setRooms] = useState(null)
  const [roomName, setRoomName] = useState('')
  const [listed, setListed] = useState(true)

  useEffect(() => {
    if (view !== 'rooms') return
    const load = () => api('/api/lobby').then((r) => setRooms(r.rooms)).catch(() => {})
    load()
    const timer = setInterval(load, 4000)
    return () => clearInterval(timer)
  }, [view])

  const fee = Math.floor((stake * modes.commission_percent) / 100)
  const share = Math.floor((stake - fee) / Math.max(1, size - 1))
  const rules = { variant, deck_size: deck, turn_seconds: turn, cheating }
  const params = { mode, size, stake: mode === 'stake' ? stake : 0, rules }
  const tooFew = deck === 36 && size * 6 > 36
  const noFree = mode === 'free' && me.free_left === 0
  const noMoney = mode === 'stake' && me.available.chips < stake
  const disabled = tooFew || noFree || noMoney || me.banned

  const VARIANT = { podkidnoy: t('Підкидний'), perevodnoy: t('Перевідний') }
  return (
    <div className="lobby">
      <div className="seg big">
        <button className={view === 'quick' ? 'on' : ''} onClick={() => setView('quick')}>{t('⚡ Швидка гра')}</button>
        <button className={view === 'rooms' ? 'on' : ''} onClick={() => setView('rooms')}>{t('🚪 Кімнати')}</button>
      </div>

      {view === 'rooms' && (
        <section className="card-box">
          <h3>{t('Відкриті кімнати')}</h3>
          {!rooms && <div className="spinner" />}
          {rooms && rooms.length === 0 && <p className="hint">{t('Поки порожньо. Створіть свою кімнату нижче 👇')}</p>}
          <ul className="list">
            {(rooms || []).map((r) => (
              <li key={r.id}>
                <div>
                  <b>{r.custom ? r.name : t('Швидка гра')}</b>
                  <small>{VARIANT[r.variant]}{r.cheating ? t(' · 🃏 Шулер') : ''} · {r.deck}{' ' + t('карт ·') + ' '}{r.turn}{t('с ·') + ' '}{r.mode === 'stake' ? t('ставка {0}', r.stake) : t('безкоштовно')}</small>
                  <small>👤 {r.players}/{r.size}{r.host ? ` · ${r.host}` : ''}</small>
                </div>
                <button className="btn small primary" disabled={r.mode === 'stake' && me.available.chips < r.stake}
                  onClick={() => send({ type: 'join', room: r.id })}>{t('Сісти')}</button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="card-box">
        <h3>{t('Режим')}</h3>
        <Seg value={mode} onChange={setMode} options={[
          ...(modes.free ? [['free', t('Безкоштовно')]] : []),
          ...(modes.stake ? [['stake', t('На фішки')]] : []),
        ]} />
        {mode === 'free' && me.free_left !== null && (
          <p className="hint">{t('Безкоштовних ігор сьогодні:') + ' '}{me.free_left}</p>
        )}
        {mode === 'stake' && (
          <>
            <h4>{t('Ставка')}</h4>
            <Seg value={stake} onChange={setStake} options={modes.stakes.map((s) => [s, `${s}`])} />
          </>
        )}
      </section>

      <section className="card-box">
        <h3>{t('Правила')}</h3>
        <Seg value={variant} onChange={setVariant} options={[['podkidnoy', t('Підкидний')], ['perevodnoy', t('Перевідний')]]} />
        <h4>{t('Гравців')}</h4>
        <Seg value={size} onChange={setSize} options={[[2, '2'], [3, '3'], [4, '4']]} />
        <h4>{t('Колода')}</h4>
        <Seg value={deck} onChange={setDeck} options={[[36, t('36 карт')], [52, t('52 карти')]]} />
        <label className="toggle cheat-toggle">
          <input type="checkbox" checked={cheating} onChange={(e) => setCheating(e.target.checked)} />
          {' ' + t('🃏 Режим «Шулер» — можна мухлювати')}
        </label>
        {cheating && <p className="hint">{t('Можна відбиватися будь-якою картою й підкидати будь-що. Помітили мухлювання — торкніться карти, і вона повернеться мухлярові.')}</p>}
        <h4>{t('Час на хід')}</h4>
        <Seg value={turn} onChange={setTurn} options={[[20, t('20 с')], [30, t('30 с')], [60, t('60 с')]]} />
      </section>

      {mode === 'stake' && (
        <section className="card-box terms">
          <div><span>{t('Ставка')}</span><b>{stake}</b></div>
          <div><span>{t('Комісія')}</span><b>{modes.commission_percent}% ({fee})</b></div>
          <div><span>{t('Можливий виграш')}</span><b className="plus">+{share}</b></div>
          <div><span>{t('Можлива втрата')}</span><b className="minus">−{stake}</b></div>
          <p className="hint">{t(
            '«Дурень» віддає ставку, решта ділять її порівну. Нічия чи скасування — ставка повертається. Ставка резервується, поки йде пошук і матч.'
          )}</p>
        </section>
      )}

      {noMoney && <p className="error">{t('Недостатньо фішок — поповніть у вкладці «Фішки».')}</p>}
      {noFree && <p className="error">{t('Безкоштовна гра на сьогодні вичерпана.')}</p>}

      {view === 'quick' ? (
        <div className="actions-col">
          <button className="btn primary big" disabled={disabled} onClick={() => send({ type: 'find', ...params })}>{t('Знайти гру')}</button>
          <p className="hint center">{t(
            'Шукаємо суперників з такими ж налаштуваннями. Якщо онлайн малий, суперників підбере система — гра почнеться за кілька секунд.'
          )}</p>
        </div>
      ) : (
        <section className="card-box">
          <h3>{t('Створити кімнату')}</h3>
          <input placeholder={t('Назва кімнати')} maxLength={40} value={roomName} onChange={(e) => setRoomName(e.target.value)} />
          <label className="toggle"><input type="checkbox" checked={listed} onChange={(e) => setListed(e.target.checked)} />{t('Показувати в списку кімнат (інакше — лише за запрошенням)')}</label>
          <button className="btn primary" disabled={disabled}
            onClick={() => send({ type: 'create', ...params, name: roomName, listed })}>{t('Створити')}</button>
        </section>
      )}
    </div>
  );
}
