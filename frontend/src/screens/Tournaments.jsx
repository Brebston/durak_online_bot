import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import { t } from '../i18n.js'

function roundName(i, total) {
  const fromEnd = total - i
  if (fromEnd === 1) return t('Фінал')
  if (fromEnd === 2) return t('Півфінал')
  if (fromEnd === 3) return t('Чвертьфінал')
  return t('Раунд {0}', i + 1)
}

export function Bracket({ tour }) {
  const total = Math.log2(tour.size)
  return (
    <div className="bracket">
      {Array.from({ length: total }).map((_, i) => {
        const games = tour.rounds[i] || []
        const n = tour.size / 2 ** (i + 1)
        return (
          <div key={i} className="b-round">
            <small>{roundName(i, total)}</small>
            {Array.from({ length: n }).map((__, j) => {
              const g = games[j]
              return (
                <div key={j} className={`b-match ${g?.me ? 'me' : ''} ${g?.status === 'playing' ? 'live' : ''}`}>
                  <div className={g?.winner === 0 ? 'w' : g?.winner === 1 ? 'l' : ''}>{g ? g.a : '—'}</div>
                  <div className={g?.winner === 1 ? 'w' : g?.winner === 0 ? 'l' : ''}>{g ? g.b : '—'}</div>
                </div>
              )
            })}
          </div>
        )
      })}
    </div>
  )
}

export default function Tournaments({ me, toast }) {
  const [list, setList] = useState(null)
  const [open, setOpen] = useState(null)
  const [now, setNow] = useState(Date.now())

  const load = () => api('/api/tournaments').then((r) => setList(r.tournaments.map((x) => ({ ...x, loaded: Date.now() })))).catch((e) => toast?.(e.message))
  useEffect(() => {
    load()
    const a = setInterval(load, 3000)
    const b = setInterval(() => setNow(Date.now()), 1000)
    return () => { clearInterval(a); clearInterval(b) }
  }, [])

  const act = (path, id) => api(path, { id }).then(load).catch((e) => toast?.(e.message))

  if (!list) return <div className="spinner" />
  if (list.length === 0) return <p className="hint center">{t('Турніри зараз вимкнені')}</p>
  return (
    <div className="tournaments">
      <p className="hint">{t('Безкоштовні турніри на вибування. Переможець отримує титул «Чемпіон турніру», чемпіонську сорочку й 300 XP. Якщо гравців не вистачає — вільні місця займають інші учасники, і турнір стартує вчасно.')}</p>
      {list.map((tr) => {
        const countdown = tr.starts_at ? Math.max(0, Math.round(tr.starts_at - tr.now - (now - tr.loaded) / 1000)) : null
        return (
          <section key={tr.id} className={`card-box tour ${tr.joined ? 'joined' : ''}`}>
            <div className="tour-head">
              <div>
                <b>{t('Турнір на {0}', tr.size)} · #{tr.id}</b>
                <small>{tr.rules.variant === 'perevodnoy' ? t('Перевідний') : t('Підкидний')} · {tr.rules.deck_size}{' ' + t('карт')} · {t('1 на 1')}</small>
              </div>
              <span className={`tag ${tr.status}`}>{
                tr.status === 'registering' ? t('Реєстрація') : tr.status === 'running' ? t('Йде') : t('Завершено')}</span>
            </div>
            {tr.status === 'registering' && (
              <>
                <div className="progress-bar"><i style={{ width: `${(100 * tr.registered) / tr.size}%` }} /></div>
                <small className="hint">
                  {t('Зареєстровано {0} з {1}', tr.registered, tr.size)}
                  {countdown !== null ? ' · ' + t('старт через {0} с', countdown) : ' · ' + t('старт після першої реєстрації')}
                </small>
                {tr.joined ? (
                  <button className="btn" onClick={() => act('/api/tournaments/unregister', tr.id)}>{t('Скасувати участь')}</button>
                ) : (
                  <button className="btn primary" disabled={me.banned} onClick={() => act('/api/tournaments/register', tr.id)}>{t('Зареєструватися')}</button>
                )}
              </>
            )}
            {tr.status !== 'registering' && (
              <>
                {tr.winner && <p className="win-line">🏆 {tr.winner}</p>}
                {tr.joined && tr.status === 'running' && (
                  <p className="hint">{tr.out ? t('Ви вибули з турніру. Дякуємо за гру!') : t('Ви в турнірі — ваш наступний матч почнеться автоматично.')}</p>
                )}
                <button className="link" onClick={() => setOpen(open === tr.id ? null : tr.id)}>{open === tr.id ? t('Сховати сітку') : t('Показати сітку')}</button>
                {open === tr.id && <Bracket tour={tr} />}
              </>
            )}
          </section>
        )
      })}
    </div>
  )
}

