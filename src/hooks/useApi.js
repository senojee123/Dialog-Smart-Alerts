import { useState, useCallback, useEffect } from 'react'

/**
 * Generic CRUD hook for any REST collection.
 * useApi('/api/devices') → { data, loading, error, fetchAll, create, update, remove }
 */
export function useApi(endpoint, { autoFetch = true } = {}) {
  const [data, setData]       = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(null)

  const fetchAll = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(endpoint)
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
      setData(await res.json())
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [endpoint])

  useEffect(() => {
    if (autoFetch) fetchAll()
  }, [fetchAll, autoFetch])

  const create = useCallback(async (item) => {
    const res = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(item),
    })
    if (!res.ok) throw new Error(await res.text())
    const created = await res.json()
    setData(prev => [created, ...prev])
    return created
  }, [endpoint])

  const update = useCallback(async (id, patch) => {
    const res = await fetch(`${endpoint}/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    })
    if (!res.ok) throw new Error(await res.text())
    const updated = await res.json()
    setData(prev => prev.map(x => x.id === id ? updated : x))
    return updated
  }, [endpoint])

  const remove = useCallback(async (id) => {
    const res = await fetch(`${endpoint}/${id}`, { method: 'DELETE' })
    if (!res.ok) throw new Error(await res.text())
    setData(prev => prev.filter(x => x.id !== id))
  }, [endpoint])

  return { data, loading, error, fetchAll, create, update, remove, setData }
}
