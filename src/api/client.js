const BASE = import.meta.env.VITE_API_BASE ?? '/api'

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
