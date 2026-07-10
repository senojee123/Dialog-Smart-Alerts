// Intercept global fetch to transparently support split deployments (Vercel + Railway)
const originalFetch = window.fetch
const API_BASE = import.meta.env.VITE_API_BASE || ''
window.fetch = (input, init) => {
  if (typeof input === 'string' && input.startsWith('/api') && API_BASE) {
    // If API_BASE is e.g. "https://my-backend.railway.app/api"
    // and input is "/api/incidents", replace "/api" prefix with API_BASE
    const targetUrl = input.replace('/api', API_BASE)
    return originalFetch(targetUrl, init)
  }
  return originalFetch(input, init)
}

import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import './theme/tokens.css'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
