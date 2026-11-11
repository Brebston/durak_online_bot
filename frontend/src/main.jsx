import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'
import './styles.css'
import './cosmetics.css'
import { tg } from './api.js'

try {
  tg?.ready()
  tg?.expand()
  tg?.setHeaderColor?.('#0f3d2e')
  tg?.setBackgroundColor?.('#0b2a20')
} catch { /* ignore */ }

createRoot(document.getElementById('root')).render(<App />)
