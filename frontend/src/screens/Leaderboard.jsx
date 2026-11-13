import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Avatar } from '../Fx.jsx'
import { t, titleText } from '../i18n.js'
import PlayerCard from './PlayerCard.jsx'

function Seg({ value, options, onChange }) {
  return (
    <div className="seg">
      {options.map(([v, l]) => (
        <button key={v} className={value === v ? 'on' : ''} onClick={() => onChange(v)}>{l}</button>
      ))}
    </div>
  )
}

export default function Leaderboard({ me, toast }) {
  const [kind, setKind] = useState('season')
  const [scope, setScope] = useState('all')
  const [data, setData] = useState(null)
  const [card, setCard] = useState(null)

  useEffect(() => {
    setData(null)
    api(`/api/leaderboard?kind=${kind}&scope=${scope}`).then(setData).catch((e) => toast?.(e.message))
  }, [kind, scope])

  const unit = kind === 'rating' ? '' : t('очк.')
  const row = (r, mine) => (
    <li key={`${mine ? 'me' : ''}${r.user_id}`} className={r.user_id === me.id ? 'me' : ''} onClick={() => setCard(r.user_id)}>
      <span className="place">{r.place <= 3 ? ['🥇', '🥈', '🥉'][r.place - 1] : r.place}</span>
      <Avatar url={r.avatar} name={r.name} size={30} />
      <div className="lb-name"><b>{r.name}</b>{r.title && <small>{titleText(r.title)}</small>}</div>
      <span className="lvl">{r.lvl}</span>
      <b className="score">{r.score} {unit}</b>
    </li>
  )
  return (
    <div className="leaderboard">
      <Seg value={kind} onChange={setKind} options={[['season', t('Сезон')], ['week', t('Тиждень')], ['rating', t('Рейтинг')]]} />
      <Seg value={scope} onChange={setScope} options={[['all', t('Усі')], ['friends', t('Друзі')]]} />
      <p className="hint">
        {kind === 'season' && t('Сезон {0}: очки за кожну гру (перемога — 3, нічия — 1). Топ-10 наприкінці місяця отримують сезонну сорочку й титул.', data?.season || '')}
        {kind === 'week' && t('Очки за останні 7 днів.')}
        {kind === 'rating' && t('Рейтинг Elo з рейтингових матчів 1 на 1.')}
      </p>
      {!data && <div className="spinner" />}
      {data && (
        <ul className="lb">
          {data.rows.length === 0 && <li className="hint">{t('Поки порожньо — зіграйте першим!')}</li>}
          {data.rows.map((r) => row(r))}
          {data.me && !data.rows.some((r) => r.user_id === me.id) && (<><li className="gap">…</li>{row(data.me, true)}</>)}
        </ul>
      )}
      {card && <PlayerCard uid={card} onClose={() => setCard(null)} toast={toast} />}
    </div>
  )
}
