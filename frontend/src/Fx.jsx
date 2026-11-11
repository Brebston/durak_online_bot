import React, { useMemo } from 'react'

export function Intro({ id }) {
  return (
    <div className={`intro in-${id}`}>
      {id === 'intro_fan' && (
        <div className="fan">
          {['14S', '14H', '14D', '14C', '6H'].map((c, i) => (
            <div key={c} className={`pcard ${c.endsWith('H') || c.endsWith('D') ? 'red' : ''}`}
              style={{ transform: `rotate(${(i - 2) * 16}deg)`, animationDelay: `${i * 60}ms` }}>
              <span className="tl">{c.startsWith('14') ? 'Т' : '6'}<br />{{ S: '♠', H: '♥', D: '♦', C: '♣' }[c.slice(-1)]}</span>
            </div>
          ))}
        </div>
      )}
      {id === 'intro_ace' ? <div className="ace">♠</div> : <div className="logo-big">♠ Дурак</div>}
    </div>
  )
}

const CONFETTI = ['#f2c14e', '#e5484d', '#3ecf8e', '#4ea1f2', '#c86bff', '#fff']

export function Victory({ id }) {
  const parts = useMemo(() => {
    const n = id === 'victory_crown' ? 0 : id === 'victory_fireworks' ? 60 : 50
    return Array.from({ length: n }, (_, i) => {
      if (id === 'victory_fireworks') {
        const burst = i % 3
        const ang = Math.random() * Math.PI * 2
        const dist = 60 + Math.random() * 90
        return {
          left: `${[25, 50, 75][burst]}%`, top: `${[30, 22, 34][burst]}%`,
          background: CONFETTI[(i + burst) % CONFETTI.length],
          '--dx': `${Math.cos(ang) * dist}px`, '--dy': `${Math.sin(ang) * dist}px`,
          animationDelay: `${burst * 0.35}s`,
        }
      }
      return {
        left: `${Math.random() * 100}%`,
        animationDuration: `${2 + Math.random() * 2.5}s`,
        animationDelay: `${Math.random() * 1.2}s`,
        background: id === 'victory_confetti' ? CONFETTI[i % CONFETTI.length] : undefined,
      }
    })
  }, [id])
  return (
    <div className={`victory vc-${id}`}>
      {id === 'victory_crown' && <div className="crown">👑</div>}
      {parts.map((st, i) => <i key={i} style={st}>{id === 'victory_stars' ? '★' : null}</i>)}
    </div>
  )
}
