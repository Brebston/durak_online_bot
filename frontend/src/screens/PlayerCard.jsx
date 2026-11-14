import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Avatar } from '../Fx.jsx'
import { t, titleText } from '../i18n.js'

export const ACH_ICON = {
  first_win: '🥇', wins_10: '🎖', wins_100: '🏅', first_transfer: '🔀', catcher_10: '🕵️', no_take_win: '🧼',
  trump_50: '🃏', win_streak_5: '🔥', four_win: '👑', ranked_10: '📈', tournament_win: '🏆', streak_7: '📅',
  level_10: '🔟',
}

const REASONS = ['Образи в чаті', 'Нечесна гра', 'Спам', 'Інше']

/** Картка гравця: рівень, рейтинг, титул, бейджі, статистика й скарга. */
export default function PlayerCard({ seat, uid, matchId, onClose, toast }) {
  const id = uid || Number((seat?.pid || '').match(/^u(\d+)$/)?.[1] || 0)
  const [p, setP] = useState(null)
  const [report, setReport] = useState(false)
  useEffect(() => {
    if (!id) return
    api(`/api/profile/${id}`).then(setP).catch(() => setP(false))
  }, [id])

  const sendReport = (reason) => {
    api('/api/report', { user_id: id, reason, match_id: matchId })
      .then(() => { toast?.(t('Скаргу надіслано. Дякуємо!')); setReport(false) })
      .catch((e) => toast?.(e.message))
  }

  const name = p?.name || seat?.name
  const title = p ? p.title : seat?.title
  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal player-card" onClick={(e) => e.stopPropagation()}>
        <div className="pc-head">
          <Avatar url={p?.avatar || seat?.avatar} name={name} size={56} />
          <div>
            <h3>{name}</h3>
            {title && <div className="title-chip">{titleText(title)}</div>}
            <small className="hint">{t('Рівень') + ' '}{p?.lvl || seat?.lvl || 1} · {t('Рейтинг') + ' '}{p?.rating || seat?.rating || 1000}</small>
          </div>
        </div>
        {p === null && id > 0 && <div className="spinner" />}
        {p && (
          <>
            <div className="stats">
              <div><b>{p.stats.games}</b><span>{t('ігор')}</span></div>
              <div><b>{p.stats.wins}</b><span>{t('перемог')}</span></div>
              <div><b>{p.stats.games ? Math.round((100 * p.stats.wins) / p.stats.games) : 0}%</b><span>{t('виграшів')}</span></div>
              <div><b>{p.stats.tournament_wins}</b><span>{t('турнірів')}</span></div>
            </div>
            {p.h2h && p.h2h.played > 0 && (
              <>
                <h4>{t('Особистий рахунок')}</h4>
                <div className="h2h">
                  <b className="plus">{p.h2h.wins}</b>
                  <span>:</span>
                  <b className="minus">{p.h2h.losses}</b>
                  <small className="hint">
                    {p.h2h.draws ? t('нічиїх: {0} · ', p.h2h.draws) : ''}
                    {t('разом зіграно {0}', p.h2h.played)}
                  </small>
                </div>
              </>
            )}
            <h4>{t('Досягнення')} · {p.achievements.length}/{p.achievements_total}</h4>
            <div className="badges">
              {p.achievements.length === 0 && <small className="hint">{t('Поки немає')}</small>}
              {p.achievements.map((a) => <span key={a.id} className="ach on" title={t(a.name)}>{ACH_ICON[a.id] || '⭐'}</span>)}
            </div>
            {!p.me && !report && <button className="link danger" onClick={() => setReport(true)}>{t('Поскаржитися')}</button>}
            {report && (
              <div className="actions-col">
                {REASONS.map((r) => <button key={r} className="btn small" onClick={() => sendReport(r)}>{t(r)}</button>)}
              </div>
            )}
          </>
        )}
        <button className="btn" onClick={onClose}>{t('Закрити')}</button>
      </div>
    </div>
  )
}
