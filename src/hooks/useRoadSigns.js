import { useState, useCallback, useRef } from 'react'
import { DEFAULT_ROAD_SIGNS } from '../mock/roadsigns.js'

const STORAGE_KEY = 'dsa-road-signs'

function load() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : DEFAULT_ROAD_SIGNS
  } catch {
    return DEFAULT_ROAD_SIGNS
  }
}

export function useRoadSigns() {
  const [signs, setSigns] = useState(load)
  const signsRef = useRef(signs)
  signsRef.current = signs

  const commit = useCallback((next) => {
    // next can be an array or an updater function
    const resolved = typeof next === 'function' ? next(signsRef.current) : next
    setSigns(resolved)
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(resolved))
    } catch {
      // storage full — ignore
    }
  }, [])

  const addSign = useCallback((sign) => {
    const entry = {
      ...sign,
      id: `RS-${Date.now()}`,
      last_updated: new Date().toISOString(),
      online: true,
    }
    commit(prev => [...prev, entry])
    return entry.id
  }, [commit])

  const updateSign = useCallback((id, patch) => {
    commit(prev => prev.map(s => s.id === id
      ? { ...s, ...patch, last_updated: new Date().toISOString() }
      : s))
  }, [commit])

  const deleteSign = useCallback((id) => {
    commit(prev => prev.filter(s => s.id !== id))
  }, [commit])

  const resetToDefaults = useCallback(() => {
    commit(DEFAULT_ROAD_SIGNS)
  }, [commit])

  return { signs, addSign, updateSign, deleteSign, resetToDefaults }
}
