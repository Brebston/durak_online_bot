import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import { t } from '../i18n.js'
import Tournaments from './Tournaments.jsx'

function Seg({ value, options, onChange }) {
  return (
    <div className="seg">
      {options.map(([v, l]) => (
        <button key={String(v)} className={value === v ? 'on' : ''} onClick={() => onChange(v)}>{l}</button>
      ))}
    </div>
  )
}

export default function Lobby({ me, send, toast, view: initialView }) {
  const modes = me.modes
  const [mode, setMode] = useState(modes.free ? 'free' : 'stake')
  const [size, setSize] = useState(2)
  const [variant, setVariant] = useState('podkidnoy')
  const [deck, setDeck] = useState(36)
  const [stake, setStake] = useState(modes.stakes[0] || 10)
  const [turn, setTurn] = useState(30)
  const [cheating, setCheating] = useState(false)
  const [view, setView] = useState(initialView || 'quick') // quick | rooms | tournaments
  const [rooms, setRooms] = useState(null)
  const [roomName, setRoomName] = useState('')
  const [listed, setListed] = useState(true)
  const [daily, setDaily] = useState(null)
  const [dailyBusy, setDailyBusy] = useState(false)
  const [tutorBusy, setTutorBusy] = useState(false)

  useEffect(() => {
    if (view !== 'quick') return
    api('/api/daily').then(setDaily).catch(() => {})
  }, [view])

  const playDaily = async () => {
    setDailyBusy(true)
    try {
      await api('/api/daily', {})
    } catch (e) { toast(e.message); setDailyBusy(false) }
  }

  const playTutorial = async () => {
    setTutorBusy(true)
    try {
      await api('/api/tutorial', {})
    } catch (e) { toast(e.message); setTutorBusy(false) }
  }

  useEffect(() => {
    if (view !== 'rooms') return
    const load = () => api('/api/lobby').then((r) => setRooms(r.rooms)).catch(() => {})
    load()
    const timer = setInterval(load, 4000)
    return () => clearInterval(timer)
  }, [view])

  const fee = Math.floor((stake * modes.commission_percent) / 100)
  const share = Math.floor((stake - fee) / Math.max(1, size - 1))
  const ranked = mode === 'ranked' && view === 'quick'
  const rules = ranked ? { variant, turn_seconds: 30 } : { variant, deck_size: deck, turn_seconds: turn, cheating }
  const params = { mode: view === 'rooms' && mode === 'ranked' ? 'free' : mode, size: ranked ? 2 : size, stake: mode === 'stake' ? stake : 0, rules }
  const tooFew = !ranked && deck === 36 && size * 6 > 36
  const noFree = params.mode === 'free' && me.free_left === 0
  const noMoney = mode === 'stake' && me.available.chips < stake
  const disabled = tooFew || noFree || noMoney || me.banned

  const VARIANT = { podkidnoy: t('Підкидний'), perevodnoy: t('Перевідний') }
  return (
    <div className="lobby">
      <div className="seg big">
        <button className={view === 'quick' ? 'on' : ''} onClick={() => setView('quick')}>{t('⚡ Швидка гра')}</button>
        <button className={view === 'rooms' ? 'on' : ''} onClick={() => setView('rooms')}>{t('🚪 Кімнати')}</button>
        {modes.tournaments !== false && <button className={view === 'tournaments' ? 'on' : ''} onClick={() => setView('tournaments')}>{t('🏆 Турніри')}</button>}
      </div>

      {view === 'quick' && !me.tutorial_done && (
        <section className="card-box tutor-box">
          <h3>{t('🎓 Навчальна гра')}</h3>
          <p className="hint">{t('Спокійна партія проти легкого бота з підказками на кожному кроці. Не витрачає денний ліміт.')}</p>
          <button className="btn primary" disabled={tutorBusy} onClick={playTutorial}>
            {tutorBusy ? t('Роздаємо…') : t('Почати навчання')}
          </button>
        </section>
      )}

      {view === 'quick' && daily && (
        <section className="card-box daily-box">
          <h3>{t('🎴 Роздача дня')}</h3>
          <p className="hint">{t('Одна й та сама роздача для всіх гравців сьогодні. Одна спроба на добу.')}</p>
          {daily.played ? (
            <>
              <p>{daily.me
                ? t('Ваш результат: {0} · місце {1}', { win: t('перемога'), draw: t('нічия'), loss: t('поразка') }[daily.me.outcome], daily.me.place)
                : t('Партію зараховано.')}</p>
              {daily.top.length > 0 && (
                <ul className="list">
                  {daily.top.slice(0, 5).map((r) => (
                    <li key={r.user_id}>
                      <div><b>{r.place}. {r.name}</b></div>
                      <small>{{ win: t('перемога'), draw: t('нічия'), loss: t('поразка') }[r.outcome]}</small>
                    </li>
                  ))}
                </ul>
              )}
            </>
          ) : (
            <button className="btn primary" disabled={dailyBusy || me.banned} onClick={playDaily}>
              {dailyBusy ? t('Роздаємо…') : t('Грати роздачу дня')}
            </button>
          )}
        </section>
      )}

      {view === 'tournaments' && <Tournaments me={me} toast={toast} />}
      {view !== 'tournaments' && (<>

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
          ...(modes.ranked && view === 'quick' ? [['ranked', t('📈 Рейтингова')]] : []),
        ]} />
        {ranked && <p className="hint">{t('1 на 1 проти суперника приблизно вашої сили. Перемога підвищує рейтинг, поразка — знижує. Ваш рейтинг:') + ' '}<b>{me.rating}</b></p>}
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
        {ranked ? (<>
          <Seg value={variant} onChange={setVariant} options={[['podkidnoy', t('Підкидний')], ['perevodnoy', t('Перевідний')]]} />
          <p className="hint">{t('Рейтингові правила: 1 на 1, 36 карт, 30 с на хід, без режиму «Шулер».')}</p>
        </>) : (<>
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
        </>)}
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
      </>)}
    </div>
  );
}
