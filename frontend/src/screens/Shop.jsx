import React, { useCallback, useEffect, useState } from 'react'
import { api, tg } from '../api.js'
import { Chip, Intro, Victory } from '../Fx.jsx'
import { sfx } from '../sounds.js'
import { t } from '../i18n.js'

const CATS = [['chips', t('⭐ Фішки')], ['back', t('Сорочки')], ['table', t('Столи')], ['emoji', t('Смайлики')], ['intro', t('Заставки')], ['victory', t('Перемога')]]

export default function Shop({ me, reload, toast }) {
  const [cat, setCat] = useState('chips')
  const [shop, setShop] = useState(null)
  const [busy, setBusy] = useState(false)
  const [preview, setPreview] = useState(null)
  const [gifting, setGifting] = useState(null)   // предмет, який даруємо
  const [friends, setFriends] = useState(null)

  const load = useCallback(() => api('/api/shop').then(setShop).catch((e) => toast(e.message)), [toast])
  useEffect(() => { load() }, [load])

  const buyStars = async (stars) => {
    setBusy(true)
    try {
      const r = await api('/api/invoice', { stars })
      if (r.link && tg?.openInvoice) {
        tg.openInvoice(r.link, (status) => {
          if (status === 'paid') { toast(t('Оплачено! Фішки зараховано.')); setTimeout(reload, 1500) }
          else if (status === 'failed') toast(t('Оплата не пройшла'))
        })
      } else if (r.link) {
        window.open(r.link, '_blank')
      } else if (r.dev_credited) {
        toast(t('DEV: зараховано {0}', r.dev_credited))
        reload()
      }
    } catch (e) { toast(e.message) } finally { setBusy(false) }
  }

  const buy = async (item) => {
    setBusy(true)
    try {
      const r = await api('/api/shop/buy', { item_id: item.id })
      setShop((s) => ({ ...s, ...r }))
      sfx.play('coin')
      toast(t('«{0}» ваше!', t(item.name)))
      reload()
    } catch (e) { toast(e.message) } finally { setBusy(false) }
  }
  const equip = async (item) => {
    try {
      const r = await api('/api/shop/equip', { item_id: item.id })
      setShop((s) => ({ ...s, ...r }))
      reload()
    } catch (e) { toast(e.message) }
  }
  const openGift = async (item) => {
    setGifting(item)
    if (!friends) {
      try {
        setFriends((await api('/api/friends')).friends)
      } catch (e) { toast(e.message); setGifting(null) }
    }
  }
  const sendGift = async (friend) => {
    setBusy(true)
    try {
      await api('/api/shop/gift', { user_id: friend.id, item_id: gifting.id })
      sfx.play('coin')
      toast(t('«{0}» подаровано: {1}', t(gifting.name), friend.name))
      setGifting(null)
      reload()
    } catch (e) { toast(e.message) } finally { setBusy(false) }
  }
  const play = (item) => {
    setPreview(item)
    setTimeout(() => setPreview(null), item.type === 'intro' ? 2000 : 3500)
  }

  return (
    <div className="shop">
      <div className="seg wrap">
        {CATS.map(([id, n]) => <button key={id} className={cat === id ? 'on' : ''} onClick={() => setCat(id)}>{n}</button>)}
      </div>

      {cat === 'chips' && (
        <>
          <section className="card-box">
            <h3>{t('Баланс:') + ' '}{me.balance.chips} <Chip /></h3>
            <p className="hint">1 ⭐ = {me.shop.rate}{' ' + t(
              'фішок. Фішки — ігрова валюта лише для цієї гри, не виводяться і не обмінюються на гроші.'
            )}</p>
          </section>
          <div className="packs">
            {me.shop.packs.map((s) => (
              <button key={s} className="pack" disabled={busy || !me.shop.enabled} onClick={() => buyStars(s)}>
                <b>{s * me.shop.rate} <Chip size={20} /></b><span>{t('фішок')}</span><em>{s} ⭐</em>
              </button>
            ))}
          </div>
          {!me.shop.enabled && <p className="error">{t('Оплата тимчасово недоступна.')}</p>}
        </>
      )}

      {cat !== 'chips' && !shop && <div className="spinner" />}
      {cat !== 'chips' && shop && (
        <div className="items">
          {shop.items.filter((i) => i.type === cat).map((item) => {
            const owned = shop.owned.includes(item.id)
            const equipped = shop.equipped[item.type] === item.id
            return (
              <div key={item.id} className={`item ${equipped ? 'equipped' : ''}`}>
                <div className="item-preview">
                  {item.type === 'back' && <div className={`back big cb-${item.id}`} />}
                  {item.type === 'table' && <div className={`table-preview tb-${item.id}`} />}
                  {item.type === 'emoji' && <div className="emoji-grid">{item.emojis.map((e) => <span key={e}>{e}</span>)}</div>}
                  {(item.type === 'intro' || item.type === 'victory') && (
                    <button className="btn small" onClick={() => play(item)}>{t('▶ Переглянути')}</button>
                  )}
                </div>
                <b>{t(item.name)}</b>
                {item.price > 0 && !item.award && !item.level && (
                  <button className="link gift-link" title={t('Подарувати другові')} onClick={() => openGift(item)}>
                    {t('🎁 Подарувати')}
                  </button>
                )}
                {equipped ? <span className="hint">{t('✓ Встановлено')}</span>
                  : owned ? (item.type === 'emoji'
                    ? <span className="hint">{t('✓ Ваше')}</span>
                    : <button className="btn small" onClick={() => equip(item)}>{t('Встановити')}</button>)
                    : item.award ? <span className="lock">{{ streak: t('🔥 7 днів поспіль'), tournament: t('🏆 Перемога в турнірі'), season: t('⭐ Топ-10 сезону') }[item.award]}</span>
                    : item.level ? <span className="lock">{t('🔒 Рівень') + ' '}{item.level}</span>
                      : <button className="btn small primary" disabled={busy || me.available.chips < item.price} onClick={() => buy(item)}>
                        {item.price} <Chip />
                      </button>}
              </div>
            );
          })}
        </div>
      )}

      {gifting && (
        <div className="overlay" onClick={() => setGifting(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>{t('🎁 Подарувати «{0}»', t(gifting.name))}</h3>
            <p className="hint">{t('Ви платите {0} фішок. Друг отримає предмет у магазин — вдягне сам.', gifting.price)}</p>
            {!friends && <div className="spinner" />}
            {friends?.length === 0 && <p className="hint">{t('Подарунки можна надсилати лише друзям.')}</p>}
            {friends?.length > 0 && (
              <ul className="list">
                {friends.map((f) => (
                  <li key={f.id}>
                    <div><b>{f.name}</b></div>
                    <button className="btn small primary" disabled={busy || me.available.chips < gifting.price}
                      onClick={() => sendGift(f)}>{gifting.price} <Chip /></button>
                  </li>
                ))}
              </ul>
            )}
            <button className="btn" onClick={() => setGifting(null)}>{t('Закрити')}</button>
          </div>
        </div>
      )}

      {preview?.type === 'intro' && <Intro id={preview.id} />}
      {preview?.type === 'victory' && <Victory id={preview.id} />}
    </div>
  );
}
