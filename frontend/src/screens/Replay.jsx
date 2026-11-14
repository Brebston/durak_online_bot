import React, { useEffect, useMemo, useState } from 'react'
import { api, label as cardLabel } from '../api.js'
import { t } from '../i18n.js'
import { Card } from './Room.jsx'

const SPEEDS = [[1, '1×'], [2, '2×'], [4, '4×']]

/** Підпис до кадру: що саме зробив гравець. */
function stepText(frame, nameOf) {
  const who = nameOf(frame.actor)
  const card = frame.action?.card ? cardLabel(frame.action.card) : ''
  if (frame.label === 'start') return t('Роздача')
  if (frame.label === 'surrender') return t('{0} здається', who)
  if (frame.label === 'afk_surrender') return t('{0} вийшов за пропущеними ходами', who)
  const late = frame.label === 'timeout' ? t(' (таймаут)') : ''
  switch (frame.action?.type) {
    case 'attack': return t('{0} кидає {1}', who, card) + late
    case 'defend': return t('{0} відбиває {1}', who, card) + late
    case 'transfer': return t('{0} переводить {1}', who, card) + late
    case 'take': return t('{0} бере карти', who) + late
    case 'pass': return t('{0}: бито', who) + late
    case 'catch': return t('{0} ловить мухляра', who) + late
    default: return who
  }
}

export default function Replay({ matchId, onClose, toast }) {
  const [data, setData] = useState(null)
  const [idx, setIdx] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)
  const [loadingReveal, setLoadingReveal] = useState(false)

  const load = (reveal) => api(`/api/replay/${matchId}${reveal ? '?reveal=1' : ''}`)
    .then((d) => { setData(d); return d })
    .catch((e) => { toast(e.message); onClose(); })

  useEffect(() => { load(false) }, [matchId])

  const frames = data?.frames || []
  const frame = frames[Math.min(idx, frames.length - 1)]

  // автопрогравання
  useEffect(() => {
    if (!playing || !frames.length) return
    const id = setInterval(() => setIdx((i) => Math.min(i + 1, frames.length - 1)), 1100 / speed)
    return () => clearInterval(id)
  }, [playing, speed, frames.length])

  // на останньому кадрі зупиняємось (окремо, щоб не чіпати стан із апдейтера setIdx)
  useEffect(() => {
    if (playing && frames.length && idx >= frames.length - 1) setPlaying(false)
  }, [playing, idx, frames.length])

  const nameOf = useMemo(() => {
    const byPid = Object.fromEntries((data?.match.players || []).map((p) => [p.pid, p]))
    return (pid) => {
      const p = byPid[pid]
      if (!p) return pid || ''
      return p.name + (p.bot ? ' 🤖' : '') + (p.you ? t(' (ви)') : '')
    }
  }, [data])

  const showCards = async () => {
    setLoadingReveal(true)
    const keep = idx
    await load(true)
    setIdx(keep)
    setLoadingReveal(false)
  }

  if (!data || !frame) return <div className="replay-screen"><div className="spinner" /></div>

  const v = frame.view
  const m = data.match
  const outcome = v.draw ? t('Нічия') : v.loser ? t('Дурень: {0}', nameOf(v.loser)) : ''

  return (
    <div className="replay-screen">
      <header className="replay-head">
        <button className="link" onClick={onClose}>{t('← Назад')}</button>
        <div>
          <b>{t('Реплей')}</b>
          <small className="hint">
            {m.rules.variant === 'perevodnoy' ? t('Перевідний') : t('Підкидний')}
            {m.rules.cheating ? t(' · 🃏 Шулер') : ''}
            {m.mode === 'stake' ? ` · ${m.stake}` : ' · free'}
            {t(' · матч {0}', m.id)}
          </small>
        </div>
      </header>

      {data.truncated_at != null && (
        <p className="hint replay-warn">
          {t('Журнал обривається на події {0} — далі матч відтворити не вдалося.', data.truncated_at)}
        </p>
      )}

      <div className="replay-board">
        <div className="replay-side">
          <div>{t('Козир')}: <b>{cardLabel(v.trump_card_shown)}</b></div>
          <div>{t('Колода')}: <b>{v.deck_count}</b></div>
          <div>{t('Бито:') + ' '}<b>{v.discard_count}</b></div>
          <div>{t('Відбій')} <b>{v.bout}</b></div>
        </div>

        <ul className="replay-players">
          {m.players.map((p) => {
            const st = v.players.find((x) => x.id === p.pid)
            return (
              <li key={p.pid} className={v.defender === p.pid ? 'def' : v.attacker === p.pid ? 'att' : ''}>
                <span>{nameOf(p.pid)}</span>
                <small>
                  {v.defender === p.pid ? t('бʼється') : v.attacker === p.pid ? t('атакує') : ''}
                  {st?.out ? ' · ' + t('вийшов') : ''}
                </small>
                {frame.hands
                  ? <div className="replay-hand">{(frame.hands[p.pid] || []).map((c) => <Card key={c} c={c} small />)}</div>
                  : <b>{st?.cards ?? 0}</b>}
              </li>
            )
          })}
        </ul>

        <div className="table-cards replay-table">
          {v.table.map(([a, d]) => (
            <div key={a} className="pair">
              <Card c={a} />
              {d && <div className="cover"><Card c={d} /></div>}
            </div>
          ))}
          {!v.table.length && <div className="table-hint">{outcome || t('Стіл порожній')}</div>}
        </div>
      </div>

      <div className="replay-step">{stepText(frame, nameOf)}</div>

      <div className="replay-controls">
        <input
          type="range" min={0} max={frames.length - 1} value={idx}
          onChange={(e) => { setPlaying(false); setIdx(Number(e.target.value)) }}
        />
        <div className="replay-buttons">
          <button className="btn small" onClick={() => { setPlaying(false); setIdx(0) }}>⏮</button>
          <button className="btn small" onClick={() => { setPlaying(false); setIdx((i) => Math.max(0, i - 1)) }}>◀</button>
          <button
            className="btn primary"
            onClick={() => {
              if (playing) { setPlaying(false); return }
              if (idx >= frames.length - 1) setIdx(0)   // з кінця — програти знову
              setPlaying(true)
            }}
          >
            {playing ? '⏸' : '▶'}
          </button>
          <button className="btn small" onClick={() => { setPlaying(false); setIdx((i) => Math.min(frames.length - 1, i + 1)) }}>▶</button>
          <span className="hint">{idx + 1}/{frames.length}</span>
        </div>
        <div className="seg">
          {SPEEDS.map(([s, lbl]) => (
            <button key={s} className={speed === s ? 'on' : ''} onClick={() => setSpeed(s)}>{lbl}</button>
          ))}
        </div>
        {!data.revealed && (
          <button className="btn small" onClick={showCards} disabled={loadingReveal}>
            {loadingReveal ? t('Відкриваємо…') : t('🂠 Показати карти всіх')}
          </button>
        )}
        {data.revealed && <small className="hint">{t('Карти відкрито. Кожне відкриття фіксується в журналі.')}</small>}
      </div>
    </div>
  );
}
