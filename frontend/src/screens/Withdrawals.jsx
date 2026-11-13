import React, { useCallback, useEffect, useState } from 'react'
import { api } from '../api.js'
import { t } from '../i18n.js'

const STATUS = {
  pending: t('Очікує схвалення'),
  approved: t('Схвалено · очікує виплати'),
  completed: t('Виконано'),
  rejected: t('Відхилено'),
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
  const canRequest = Number.isSafeInteger(chips) && chips > 0 && chips % chipsPerStar === 0 &&
    chips <= me.available.chips && !busy && !hasOpenRequest

  const submit = async () => {
    if (!canRequest) return
    setBusy(true)
    try {
      const r = await api('/api/withdrawals', { chips })
      toast(t('Заявку №{0} на {1} ⭐ створено', r.id, r.stars))
      setChipsInput('')
      await Promise.all([load(), reload()])
    } catch (e) { toast(e.message) } finally { setBusy(false) }
  }

  return (
    <div className="profile">
      <section className="card-box">
        <h3>{t('Виведення в Telegram Stars')}</h3>
        <p className="hint">{t('Заявка буде оформлена на ваш Telegram-акаунт:')}{' '}<b>{me.name}</b>
          {' · ID '}{me.id}{me.username ? ` · @${me.username}` : ''}.</p>
        <p className="hint">{t('Доступно:')}{' '}<b>{me.available.chips}</b>{' '}{t('фішок · курс: 1 ⭐ =')}{' '}{chipsPerStar}{' '}{t('фішок')}</p>
        <input type="number" min={chipsPerStar} step={chipsPerStar} max={me.available.chips}
          placeholder={t('Сума фішок (кратно {0})', chipsPerStar)} value={chipsInput}
          onChange={(e) => setChipsInput(e.target.value)} />
        {Number.isSafeInteger(chips) && chips > 0 && chips % chipsPerStar === 0 && (
          <p className="hint">{t('До виплати:')}{' '}<b>{chips / chipsPerStar} ⭐</b>
            {me.withdrawal?.eur_per_star ? ` · ${t('приблизно €{0}', (chips / chipsPerStar * me.withdrawal.eur_per_star).toFixed(2))}` : ''}</p>
        )}
        <button className="btn primary" disabled={!canRequest} onClick={submit}>
          {busy ? t('Надсилання…') : t('Подати заявку')}
        </button>
        {hasOpenRequest && <p className="hint">{t('У вас уже є відкрита заявка. Дочекайтеся її завершення або відхилення.')}</p>}
      </section>

      <section className="card-box">
        <h3>{t('Як це працює')}</h3>
        <ol>
          <li>{t('Вкажіть суму фішок. Вона має бути кратною {0}; курс показаний над полем.', chipsPerStar)}</li>
          <li>{t('Після надсилання сума резервується і тимчасово недоступна для гри та покупок.')}</li>
          <li>{t('Адміністратор перевірить заявку. Після схвалення він вручну надішле Stars у Telegram на ваш акаунт.')}</li>
          <li>{t('Після позначення виплати як виконаної фішки списуються. Якщо заявку відхилять, резерв повернеться на баланс.')}</li>
        </ol>
        <p className="hint">{t('Схвалення не означає, що Stars уже надіслані. Орієнтовна сума в євро, якщо показана, не є гарантованою ціною.')}</p>
      </section>

      <section className="card-box">
        <h3>{t('Мої заявки')}</h3>
        <ul className="list">
          {requests.length === 0 && <li className="hint">{t('Заявок ще немає')}</li>}
          {requests.map((r) => (
            <li key={r.id}><div><b>№{r.id} · {STATUS[r.status] || r.status}</b>
              <small>{new Date(r.created_at * 1000).toLocaleString()} · {r.chips} {t('фішок')} → {r.stars} ⭐
                {r.eur_estimate != null ? ` · ${t('оцінка €{0}', Number(r.eur_estimate).toFixed(2))}` : ''}</small>
              {r.decision_note && <small>{t('Причина:')} {r.decision_note}</small>}
              {r.payout_reference && <small>{t('Підтвердження виплати:')} {r.payout_reference}</small>}
            </div></li>
          ))}
        </ul>
      </section>
    </div>
  )
}
