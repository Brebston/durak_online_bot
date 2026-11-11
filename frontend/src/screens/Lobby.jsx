import React, { useEffect, useState } from 'react'
import { api } from '../api.js'

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
  const [view, setView] = useState('quick') // quick | rooms
  const [rooms, setRooms] = useState(null)
  const [roomName, setRoomName] = useState('')
  const [listed, setListed] = useState(true)

  useEffect(() => {
    if (view !== 'rooms') return
    const load = () => api('/api/lobby').then((r) => setRooms(r.rooms)).catch(() => {})
    load()
    const t = setInterval(load, 4000)
    return () => clearInterval(t)
  }, [view])

  const fee = Math.floor((stake * modes.commission_percent) / 100)
  const share = Math.floor((stake - fee) / Math.max(1, size - 1))
  const rules = { variant, deck_size: deck, turn_seconds: turn }
  const params = { mode, size, stake: mode === 'stake' ? stake : 0, rules }
  const tooFew = deck === 36 && size * 6 > 36
  const noFree = mode === 'free' && me.free_left === 0
  const noMoney = mode === 'stake' && me.available.chips < stake
  const disabled = tooFew || noFree || noMoney || me.banned

  const VARIANT = { podkidnoy: 'Підкидний', perevodnoy: 'Перевідний' }
  return (
    <div className="lobby">
      <div className="seg big">
        <button className={view === 'quick' ? 'on' : ''} onClick={() => setView('quick')}>⚡ Швидка гра</button>
        <button className={view === 'rooms' ? 'on' : ''} onClick={() => setView('rooms')}>🚪 Кімнати</button>
      </div>

      {view === 'rooms' && (
        <section className="card-box">
          <h3>Відкриті кімнати</h3>
          {!rooms && <div className="spinner" />}
          {rooms && rooms.length === 0 && <p className="hint">Поки порожньо. Створіть свою кімнату нижче 👇</p>}
          <ul className="list">
            {(rooms || []).map((r) => (
              <li key={r.id}>
                <div>
                  <b>{r.custom ? r.name : 'Швидка гра'}</b>
                  <small>{VARIANT[r.variant]} · {r.deck} карт · {r.turn}с · {r.mode === 'stake' ? `ставка ${r.stake}` : 'безкоштовно'}</small>
                  <small>👤 {r.players}/{r.size}{r.host ? ` · ${r.host}` : ''}</small>
                </div>
                <button className="btn small primary" disabled={r.mode === 'stake' && me.available.chips < r.stake}
                  onClick={() => send({ type: 'join', room: r.id })}>Сісти</button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="card-box">
        <h3>Режим</h3>
        <Seg value={mode} onChange={setMode} options={[
          ...(modes.free ? [['free', 'Безкоштовно']] : []),
          ...(modes.stake ? [['stake', 'На фішки']] : []),
        ]} />
        {mode === 'free' && me.free_left !== null && (
          <p className="hint">Безкоштовних ігор сьогодні: {me.free_left}</p>
        )}
        {mode === 'stake' && (
          <>
            <h4>Ставка</h4>
            <Seg value={stake} onChange={setStake} options={modes.stakes.map((s) => [s, `${s}`])} />
          </>
        )}
      </section>

      <section className="card-box">
        <h3>Правила</h3>
        <Seg value={variant} onChange={setVariant} options={[['podkidnoy', 'Підкидний'], ['perevodnoy', 'Перевідний']]} />
        <h4>Гравців</h4>
        <Seg value={size} onChange={setSize} options={[[2, '2'], [3, '3'], [4, '4']]} />
        <h4>Колода</h4>
        <Seg value={deck} onChange={setDeck} options={[[36, '36 карт'], [52, '52 карти']]} />
        <h4>Час на хід</h4>
        <Seg value={turn} onChange={setTurn} options={[[20, '20 с'], [30, '30 с'], [60, '60 с']]} />
      </section>

      {mode === 'stake' && (
        <section className="card-box terms">
          <div><span>Ставка</span><b>{stake}</b></div>
          <div><span>Комісія</span><b>{modes.commission_percent}% ({fee})</b></div>
          <div><span>Можливий виграш</span><b className="plus">+{share}</b></div>
          <div><span>Можлива втрата</span><b className="minus">−{stake}</b></div>
          <p className="hint">«Дурень» віддає ставку, решта ділять її порівну. Нічия чи скасування — ставка повертається.
            Ставка резервується, поки йде пошук і матч.</p>
        </section>
      )}

      {noMoney && <p className="error">Недостатньо фішок — поповніть у вкладці «Фішки».</p>}
      {noFree && <p className="error">Безкоштовна гра на сьогодні вичерпана.</p>}

      {view === 'quick' ? (
        <div className="actions-col">
          <button className="btn primary big" disabled={disabled} onClick={() => send({ type: 'find', ...params })}>
            Знайти гру
          </button>
          <p className="hint center">Шукаємо суперників з такими ж налаштуваннями. Якщо онлайн малий, суперників
            підбере система — гра почнеться за кілька секунд.</p>
        </div>
      ) : (
        <section className="card-box">
          <h3>Створити кімнату</h3>
          <input placeholder="Назва кімнати" maxLength={40} value={roomName} onChange={(e) => setRoomName(e.target.value)} />
          <label className="toggle"><input type="checkbox" checked={listed} onChange={(e) => setListed(e.target.checked)} />
            Показувати в списку кімнат (інакше — лише за запрошенням)</label>
          <button className="btn primary" disabled={disabled}
            onClick={() => send({ type: 'create', ...params, name: roomName, listed })}>Створити</button>
        </section>
      )}
    </div>
  )
}
