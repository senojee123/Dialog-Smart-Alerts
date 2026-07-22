const BASE = import.meta.env.VITE_API_BASE ?? '/api'

// Backend origin without the trailing /api — used to resolve relative media
// paths (e.g. incident.incident_media = "/uploads/x.jpg") when the frontend
// is deployed separately from the backend (e.g. Vercel + Railway), so an
// <img> tag doesn't resolve them against the frontend's own origin instead.
const ORIGIN = BASE.replace(/\/api\/?$/, '')

export function resolveMediaUrl(path) {
  if (!path) return path
  if (/^https?:\/\//i.test(path)) return path
  return `${ORIGIN}${path}`
}

export async function apiFetch(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })
  if (!res.ok) {
    const body = await res.text()
    throw new Error(`${res.status} ${res.statusText}: ${body}`)
  }
  return res.json()
}

export const api = {
  get:    (path) => apiFetch(path),
  post:   (path, body) => apiFetch(path, { method: 'POST',  body: JSON.stringify(body) }),
  put:    (path, body) => apiFetch(path, { method: 'PUT',   body: JSON.stringify(body) }),
  delete: (path)       => apiFetch(path, { method: 'DELETE' }),
  patch:  (path, body) => apiFetch(path, { method: 'PATCH', body: JSON.stringify(body) }),
}
