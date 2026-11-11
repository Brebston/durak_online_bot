import React, { useCallback, useEffect, useState } from 'react'
import { api, tg } from '../api.js'
import { Chip, Intro, Victory } from '../Fx.jsx'
import { sfx } from '../sounds.js'

const CATS = [['chips', '⭐ Фішки'], ['back', 'Сорочки'], ['table', 'Столи'], ['emoji', 'Смайлики'], ['intro', 'Заставки'], ['victory', 'Перемога']]

export default function Shop({ me, reload, toast }) {
  const [cat, setCat] = useState('chips')
  const [shop, setShop] = useState(null)
  const [busy, setBusy] = useState(false)
  const [preview, setPreview] = useState(null)

  const load = useCallback(() => api('/api/shop').then(setShop).catch((e) => toast(e.message)), [toast])
  useEffect(() => { load() }, [load])

  const buyStars = async (stars) => {
    setBusy(true)
    try {
      const r = await api('/api/invoice', { stars })
      if (r.link && tg?.openInvoice) {
        tg.openInvoice(r.link, (status) => {
          if (status === 'paid') { toast('Оплачено! Фішки зараховано.'); setTimeout(reload, 1500) }
          else if (status === 'failed') toast('Оплата не пройшла')
        })
      } else if (r.link) {
        window.open(r.link, '_blank')
      } else if (r.dev_credited) {
        toast(`DEV: зараховано ${r.dev_credited}`)
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
      toast(`«${item.name}» ваше!`)
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
            <h3>Баланс: {me.balance.chips} <Chip /></h3>
            <p className="hint">1 ⭐ = {me.shop.rate} фішок. На фішки можна грати, купувати оформлення або подати
              заявку на ручну виплату в розділі «Вивід». Виплату перевіряє й надсилає адміністратор.</p>
          </section>
          <div className="packs">
            {me.shop.packs.map((s) => (
              <button key={s} className="pack" disabled={busy || !me.shop.enabled} onClick={() => buyStars(s)}>
                <b>{s * me.shop.rate} <Chip size={20} /></b><span>фішок</span><em>{s} ⭐</em>
              </button>
            ))}
          </div>
          {!me.shop.enabled && <p className="error">Оплата тимчасово недоступна.</p>}
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
                    <button className="btn small" onClick={() => play(item)}>▶ Переглянути</button>
                  )}
                </div>
                <b>{item.name}</b>
                {equipped ? <span className="hint">✓ Встановлено</span>
                  : owned ? (item.type === 'emoji'
                    ? <span className="hint">✓ Ваше</span>
                    : <button className="btn small" onClick={() => equip(item)}>Встановити</button>)
                    : <button className="btn small primary" disabled={busy || me.available.chips < item.price} onClick={() => buy(item)}>
                      {item.price} <Chip />
                    </button>}
              </div>
            )
          })}
        </div>
      )}

      {preview?.type === 'intro' && <Intro id={preview.id} />}
      {preview?.type === 'victory' && <Victory id={preview.id} />}
    </div>
  )
}
