import React, { useCallback, useEffect, useState } from 'react'
import { api } from '../api.js'

const STATUS = {
  pending: 'Очікує схвалення',
  approved: 'Схвалено · очікує виплати',
  completed: 'Виконано',
  rejected: 'Відхилено',
}

export default function Withdrawals({ me, reload, toast }) {
  const [requests, setRequests] = useState([])
  const [chipsInput, setChipsInput] = useState('')
  const [busy, setBusy] = useState(false)
  const load = useCallback(() => api('/api/withdrawals').then((r) => setRequests(r.requests)).catch((e) => toast(e.message)), [toast])

  useEffect(() => {
    load()
    const timer = setInterval(load, 30000)
    return () => clearInterval(timer)
  }, [load])

  const chipsPerStar = me.withdrawal?.stars_per_chips || me.shop.rate
  const chips = Number(chipsInput)
  const hasOpenRequest = requests.some((r) => ['pending', 'approved'].includes(r.status))
  const canRequest = Number.isInteger(chips) && chips > 0 && chips % chipsPerStar === 0 &&
    chips <= me.available.chips && !busy && !hasOpenRequest

  const submit = async () => {
    if (!canRequest) return
    setBusy(true)
    try {
      const r = await api('/api/withdrawals', { chips })
      toast(`Заявку №${r.id} на ${r.stars} ⭐ створено`)
      setChipsInput('')
      await Promise.all([load(), reload()])
    } catch (e) { toast(e.message) } finally { setBusy(false) }
  }

  return (
    <div className="profile">
      <section className="card-box">
        <h3>Виведення в Telegram Stars</h3>
        <p className="hint">Заявка буде оформлена на ваш Telegram-акаунт: <b>{me.name}</b>
          {' · ID '}{me.id}{me.username ? ` · @${me.username}` : ''}.</p>
        <p className="hint">Доступно: <b>{me.available.chips}</b> фішок · курс: 1 ⭐ = {chipsPerStar} фішок.</p>
        <input type="number" min={chipsPerStar} step={chipsPerStar} max={me.available.chips}
          placeholder={`Сума фішок (кратно ${chipsPerStar})`} value={chipsInput}
          onChange={(e) => setChipsInput(e.target.value)} />
        {Number.isInteger(chips) && chips > 0 && chips % chipsPerStar === 0 && (
          <p className="hint">До виплати: <b>{chips / chipsPerStar} ⭐</b>
            {me.withdrawal?.eur_per_star ? ` · приблизно €${(chips / chipsPerStar * me.withdrawal.eur_per_star).toFixed(2)}` : ''}</p>
        )}
        <button className="btn primary" disabled={!canRequest} onClick={submit}>
          {busy ? 'Надсилання…' : 'Подати заявку'}
        </button>
        {hasOpenRequest && <p className="hint">У вас уже є відкрита заявка. Дочекайтеся її завершення або відхилення.</p>}
      </section>

      <section className="card-box">
        <h3>Як це працює</h3>
        <ol>
          <li>Вкажіть суму фішок. Вона має бути кратною {chipsPerStar}; курс показаний над полем.</li>
          <li>Після надсилання сума резервується і тимчасово недоступна для гри та покупок.</li>
          <li>Адміністратор перевірить заявку. Після схвалення він вручну надішле Stars у Telegram на ваш акаунт.</li>
          <li>Статус «Виконано» з’явиться після того, як адміністратор зафіксує відправлення. Якщо заявку відхилять, резерв фішок повернеться.</li>
        </ol>
        <p className="hint">Схвалення не означає, що Stars уже надіслані. Орієнтовна сума в євро, якщо показана, не є гарантованою ціною.</p>
      </section>

      <section className="card-box">
        <h3>Мої заявки</h3>
        <ul className="list">
          {requests.length === 0 && <li className="hint">Заявок ще немає</li>}
          {requests.map((r) => (
            <li key={r.id}><div><b>№{r.id} · {STATUS[r.status]}</b>
              <small>{new Date(r.created_at * 1000).toLocaleString('uk-UA')} · {r.chips} фішок → {r.stars} ⭐
                {r.eur_estimate != null ? ` · оцінка €${Number(r.eur_estimate).toFixed(2)}` : ''}</small>
              {r.decision_note && <small>Причина: {r.decision_note}</small>}
            </div></li>
          ))}
        </ul>
      </section>
    </div>
  )
}
