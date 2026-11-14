import React, { useCallback, useEffect, useRef, useState } from 'react'
import { api, GameSocket, haptic, tg } from './api.js'
import { Chip, Intro } from './Fx.jsx'
import { sfx } from './sounds.js'
import Lobby from './screens/Lobby.jsx'
import Room from './screens/Room.jsx'
import Profile from './screens/Profile.jsx'
import Shop from './screens/Shop.jsx'
import Friends from './screens/Friends.jsx'
import Admin from './screens/Admin.jsx'
import Leaderboard from './screens/Leaderboard.jsx'
import Withdrawals from './screens/Withdrawals.jsx'
import Replay from './screens/Replay.jsx'
import { lang, t } from './i18n.js'

export default function App() {
  const [me, setMe] = useState(null)
  const [err, setErr] = useState('')
  const [tab, setTab] = useState('play')
  const [room, setRoom] = useState(null)
  const [online, setOnline] = useState('offline')
  const [invite, setInvite] = useState(null)
  const [dm, setDm] = useState(null) // останнє вхідне повідомлення (для живого оновлення чату)
  const [showIntro, setShowIntro] = useState(true)
  const [tick, setTick] = useState(0) // зміни в друзях/повідомленнях
  const [daily, setDaily] = useState(null) // нагорода за серію днів
  const [lobbyView, setLobbyView] = useState('quick')
  const [replay, setReplay] = useState(null) // id матчу, який переглядаємо
  const sock = useRef(null)
  const lastFind = useRef(null)

  const loadMe = useCallback(() => api('/api/me').then((m) => {
    sfx.setEnabled(m.settings.sound)
    if (m.daily) setDaily(m.daily)
    setMe(m)
    // мова інтерфейсу потрібна й боту (повідомлення в Telegram)
    if (m.lang !== lang) api('/api/lang', { lang }).catch(() => {})
  }).catch((e) => setErr(e.message)), [])

  const toast = useCallback((m) => {
    setErr(m)
    setTimeout(() => setErr((x) => (x === m ? '' : x)), 3500)
  }, [])

  useEffect(() => {
    loadMe()
    const introTimer = setTimeout(() => setShowIntro(false), 2000)
    const joinId = tg?.initDataUnsafe?.start_param?.replace(/^room_/, '') ||
      new URLSearchParams(location.search).get('room')
    let joined = false
    sock.current = new GameSocket((m) => {
      if (m.type === 'hello' && joinId && !joined) {
        joined = true
        sock.current.send({ type: 'join', room: joinId })
      } else if (m.type === 'room') {
        setRoom(m)
        if (m.room.status === 'finished') loadMe()
      } else if (m.type === 'chat') {
        if (m.msg.emoji) sfx.play('emoji')
        setRoom((r) => (r && r.room.id === m.room
          ? { ...r, room: { ...r.room, chat: [...(r.room.chat || []), m.msg].slice(-60) } } : r))
      } else if (m.type === 'left') {
        setRoom(null)
        loadMe()
      } else if (m.type === 'xp') {
        if (m.levelup) { sfx.play('achievement'); toast(t('🎉 Новий рівень {0}!', m.level)) } else toast(`+${m.gain} XP`)
        loadMe()
      } else if (m.type === 'progress') {
        const lines = [
          ...(m.quests || []).map((q) => t('✅ Завдання виконано: +{0} XP', q.reward)),
          ...(m.achievements || []).map((a) => t('🏅 Нове досягнення: {0}', t(a.name))),
        ]
        if (m.rating) lines.push(t('📈 Рейтинг: {0} ({1})', m.rating.value, (m.rating.delta >= 0 ? '+' : '') + m.rating.delta))
        if (m.achievements?.length) sfx.play('achievement')
        if (lines.length) setTimeout(() => toast(lines.join(' · ')), 1200)
        loadMe()
      } else if (m.type === 'tournament') {
        if (m.event === 'started') toast(t('🏆 Турнір почався! Ваш матч ось-ось стартує.'))
        else if (m.event === 'out') toast(t('Ви вибули з турніру. Дякуємо за гру!'))
        else if (m.event === 'won') { sfx.play('win'); toast(t('🏆 Ви виграли турнір! Титул і чемпіонська сорочка — ваші.')) }
        else if (m.event === 'finished') toast(t('Турнір завершено. Переможець: {0}', m.winner))
        loadMe()
      } else if (m.type === 'balance') {
        loadMe()
      } else if (m.type === 'invite') {
        haptic('heavy')
        setInvite(m)
      } else if (m.type === 'dm') {
        setDm(m.msg)
        setTick((n) => n + 1)
        toast(`💬 ${m.msg.from_name}: ${m.msg.text.slice(0, 60)}`)
        loadMe()
      } else if (m.type === 'friends') {
        setTick((n) => n + 1)
        toast(m.event === 'accepted' || m.event === 'friends' ? t('{0} тепер ваш друг', m.from) : t('{0} хоче додати вас у друзі', m.from))
        loadMe()
      } else if (m.type === 'error') {
        toast(m.key ? t(m.key, ...(m.args || []).map((a) => t(a))) : t(m.message))
      }
    }, setOnline)
    return () => { clearTimeout(introTimer); sock.current.close() }
  }, [loadMe, toast])

  const send = (msg) => {
    if (msg.type === 'find') lastFind.current = msg
    sock.current.send(msg)
  }

  const intro = showIntro && me && <Intro id={me.cosmetics?.intro || 'intro_classic'} />
  const inviteModal = invite && (
    <div className="overlay">
      <div className="modal">
        <h3>{t('🃏 Запрошення')}</h3>
        <p><b>{invite.from}</b>{' ' + t('кличе вас у') + ' '}{invite.variant === 'perevodnoy' ? t('перевідного') : t('підкидного')}{' ' + t('на') + ' '}{invite.size}
          {invite.mode === 'stake' ? t(', ставка {0}', invite.stake) : t(', безкоштовно')}</p>
        <div className="actions-col">
          <button className="btn primary" onClick={() => { send({ type: 'join', room: invite.room }); setInvite(null) }}>{t('Приєднатися')}</button>
          <button className="btn" onClick={() => setInvite(null)}>{t('Не зараз')}</button>
        </div>
      </div>
    </div>
  )

  if (!me) {
    return (
      <div className="center-screen">
        {err ? (
          <div className="actions-col center">
            <p className="error">{err}</p>
            <button className="btn" onClick={() => location.reload()}>{t('Спробувати знову')}</button>
          </div>
        ) : <div className="spinner" />}
      </div>
    );
  }

  if (room && room.room.status !== 'cancelled') {
    return (
      <>
        <Room
          data={room}
          me={me}
          send={send}
          toast={toast}
          onExit={() => {
            send({ type: 'leave' })
            if (room.room.tournament) { setTab('play'); setLobbyView('tournaments') }
            setRoom(null)
          }}
          onAgain={() => { setRoom(null); if (lastFind.current) send(lastFind.current) }}
        />
        {err && <div className="toast">{err}</div>}
        {inviteModal}
        {online !== 'online' && <div className="offline">{t('Перепідключення…')}</div>}
      </>
    );
  }

  if (replay) {
    return (
      <>
        <Replay matchId={replay} onClose={() => setReplay(null)} toast={toast} />
        {err && <div className="toast">{err}</div>}
      </>
    );
  }

  const badge = (me.friend_requests || 0) + (me.unread || 0)
  const tabs = [
    ['play', '🃏', t('Грати')],
    ['top', '🏆', t('Топ')],
    ['friends', '👥', t('Друзі'), badge],
    ['shop', '🛍', t('Магазин')],
    ['withdrawals', '⭐', t('Вивід')],
    ['profile', '👤', t('Кабінет')],
    ...(me.is_admin ? [['admin', '🛠', t('Адмін')]] : []),
  ]
  return (
    <div className="app">
      {intro}
      <header className="topbar">
        <div className="logo">{t('♠ Дурак') + ' '}<span className="lvl" title={t('Рівень')}>{me.progress?.level}</span></div>
        <div className="balance" onClick={() => setTab('shop')}>
          {me.balance.chips} <Chip />
        </div>
      </header>
      <main className="content">
        {tab === 'play' && <Lobby key={lobbyView} me={me} send={send} toast={toast} view={lobbyView} />}
        {tab === 'top' && <Leaderboard me={me} toast={toast} />}
        {tab === 'friends' && <Friends me={me} toast={toast} reloadMe={loadMe} incoming={dm} tick={tick} />}
        {tab === 'shop' && <Shop me={me} reload={loadMe} toast={toast} />}
        {tab === 'withdrawals' && <Withdrawals me={me} reload={loadMe} toast={toast} />}
        {tab === 'profile' && <Profile me={me} reload={loadMe} toast={toast} onReplay={setReplay} />}
        {tab === 'admin' && me.is_admin && <Admin me={me} toast={toast} reloadMe={loadMe} />}
      </main>
      <nav className="tabbar">
        {tabs.map(([id, icon, name, n]) => (
          <button key={id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}>
            <span>{icon}{n ? <em className="dot">{n}</em> : null}</span>{name}
          </button>
        ))}
      </nav>
      {err && <div className="toast">{err}</div>}
      {inviteModal}
      {daily && !showIntro && (
        <div className="overlay" onClick={() => setDaily(null)}>
          <div className="modal daily" onClick={(e) => e.stopPropagation()}>
            <div className="streak-fire">🔥 {daily.streak}</div>
            <h3>{daily.streak > 1 ? t('{0} днів поспіль!', daily.streak) : t('З поверненням!')}</h3>
            <div className="streak-days">
              {Array.from({ length: 7 }).map((_, i) => <span key={i} className={i < Math.min(daily.streak, 7) ? 'on' : ''}>{i + 1}</span>)}
            </div>
            <p className="plus big">+{daily.xp} XP</p>
            {daily.item && <p>{t('🎁 Нагорода за тиждень: сорочка «Тижнева серія»!')}</p>}
            <p className="hint">{t('Заходьте щодня — нагорода росте до 7-го дня. Пропуск дня обнуляє серію.')}</p>
            <button className="btn primary" onClick={() => setDaily(null)}>{t('Забрати')}</button>
          </div>
        </div>
      )}
      {online !== 'online' && <div className="offline">{t('Підключення…')}</div>}
    </div>
  );
}
