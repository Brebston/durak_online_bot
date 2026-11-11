import React, { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api.js'

export default function Friends({ me, toast, reloadMe, incoming, tick }) {
  const [data, setData] = useState(null)
  const [q, setQ] = useState('')
  const [found, setFound] = useState(null)
  const [chatWith, setChatWith] = useState(null)

  const load = useCallback(() => api('/api/friends').then(setData).catch((e) => toast(e.message)), [toast])
  useEffect(() => { load() }, [load])
  useEffect(() => { if (tick) load() }, [tick, load])

  useEffect(() => {
    if (q.trim().length < 2) { setFound(null); return }
    const t = setTimeout(() => api(`/api/users/search?q=${encodeURIComponent(q)}`).then((r) => setFound(r.users)).catch(() => {}), 300)
    return () => clearTimeout(t)
  }, [q])

  const request = async (u) => {
    try {
      const r = await api('/api/friends/request', { user_id: u.id })
      toast(r.status === 'friends' ? `${u.name} тепер ваш друг` : 'Заявку надіслано')
      setFound((list) => list?.map((x) => (x.id === u.id ? { ...x, requested: true, friend: r.status === 'friends' } : x)))
      load()
    } catch (e) { toast(e.message) }
  }
  const respond = async (u, accept) => {
    await api('/api/friends/respond', { user_id: u.id, accept }).catch((e) => toast(e.message))
    load(); reloadMe()
  }
  const remove = async (u) => {
    await api('/api/friends/remove', { user_id: u.id }).catch((e) => toast(e.message))
    setChatWith(null); load()
  }

  if (chatWith) return <Dialog friend={chatWith} me={me} toast={toast} back={() => { setChatWith(null); load(); reloadMe() }} incoming={incoming} onRemove={remove} />

  return (
    <div className="friends">
      <section className="card-box">
        <input placeholder="🔍 Пошук гравців: імʼя, @username або ID" value={q} onChange={(e) => setQ(e.target.value)} />
        {found && (
          <ul className="list">
            {found.length === 0 && <li className="hint">Нікого не знайдено</li>}
            {found.map((u) => (
              <li key={u.id}>
                <div><b><span className={`online ${u.online ? 'on' : ''}`} />{u.name}</b>
                  <small>{u.username ? `@${u.username} · ` : ''}ID {u.id}</small></div>
                {u.friend ? <span className="hint">друг</span>
                  : <button className="btn small" disabled={u.requested} onClick={() => request(u)}>{u.requested ? 'Надіслано' : '+ Додати'}</button>}
              </li>
            ))}
          </ul>
        )}
      </section>

      {data?.incoming?.length > 0 && (
        <section className="card-box">
          <h3>Заявки в друзі</h3>
          <ul className="list">
            {data.incoming.map((u) => (
              <li key={u.id}>
                <div><b>{u.name}</b><small>{u.username ? `@${u.username}` : `ID ${u.id}`}</small></div>
                <div className="row">
                  <button className="btn small primary" onClick={() => respond(u, true)}>Прийняти</button>
                  <button className="btn small" onClick={() => respond(u, false)}>✕</button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="card-box">
        <h3>Друзі {data ? `(${data.friends.length})` : ''}</h3>
        {!data && <div className="spinner" />}
        {data && data.friends.length === 0 && <p className="hint">Знайдіть друзів через пошук вище. Запросити друга в гру можна з кімнати очікування.</p>}
        <ul className="list">
          {(data?.friends || []).map((f) => (
            <li key={f.id} onClick={() => setChatWith(f)}>
              <div><b><span className={`online ${f.online ? 'on' : ''}`} />{f.name}</b>
                <small>{f.online ? 'в мережі' : 'не в мережі'}</small></div>
              <span>{f.unread ? <em className="dot static">{f.unread}</em> : '💬'}</span>
            </li>
          ))}
        </ul>
        {data?.outgoing?.length > 0 && <p className="hint">Очікують підтвердження: {data.outgoing.map((u) => u.name).join(', ')}</p>}
      </section>
    </div>
  )
}

function Dialog({ friend, me, toast, back, incoming, onRemove }) {
  const [msgs, setMsgs] = useState(null)
  const [text, setText] = useState('')
  const listRef = useRef(null)
  const load = useCallback(() => api(`/api/messages/${friend.id}`).then((r) => setMsgs(r.messages)).catch((e) => toast(e.message)), [friend.id, toast])
  useEffect(() => { load() }, [load])
  useEffect(() => { if (incoming?.from_id === friend.id) load() }, [incoming, friend.id, load])
  useEffect(() => { listRef.current?.scrollTo(0, 1e6) }, [msgs])
  const send = async (e) => {
    e.preventDefault()
    if (!text.trim()) return
    try {
      const r = await api('/api/messages', { to: friend.id, text })
      setMsgs((m) => [...(m || []), r.message])
      setText('')
    } catch (err) { toast(err.message) }
  }
  return (
    <div className="dialog">
      <div className="row between">
        <button className="link" onClick={back}>← Друзі</button>
        <b>{friend.name}</b>
        <button className="link danger" onClick={() => onRemove(friend)}>Видалити</button>
      </div>
      <div className="dm-list" ref={listRef}>
        {!msgs && <div className="spinner" />}
        {msgs && msgs.length === 0 && <p className="hint center">Напишіть першим 👋</p>}
        {(msgs || []).map((m) => (
          <div key={m.id} className={`dm ${m.from_id === me.id ? 'mine' : ''}`}>
            {m.text}<small>{new Date(m.created_at * 1000).toLocaleTimeString('uk-UA', { hour: '2-digit', minute: '2-digit' })}</small>
          </div>
        ))}
      </div>
      <form className="row" onSubmit={send}>
        <input value={text} maxLength={500} placeholder="Повідомлення…" onChange={(e) => setText(e.target.value)} />
        <button className="btn small primary" type="submit">➤</button>
      </form>
    </div>
  )
}
