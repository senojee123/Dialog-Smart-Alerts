/**
 * Simulation API client + helpers.
 * All simulated detections flow through the same ingestion contract as real
 * devices (POST /api/events), tagged source="simulation".
 */

async function call(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    let msg = `${res.status}`
    try { msg = (await res.json()).detail || msg } catch { try { msg = await res.text() } catch {} }
    throw new Error(msg)
  }
  return res.status === 204 ? null : res.json()
}

export const simulateEvent  = (body) => call('POST', '/api/simulate/event', body)
export const startScenario  = (body) => call('POST', '/api/simulate/scenario', body)
export const stopScenario   = (id)   => call('POST', `/api/simulate/scenario/${id}/stop`)
export const listScenarios  = ()     => call('GET',  '/api/simulate/scenarios')
export const resetSimulation = ()    => call('POST', '/api/simulate/reset')

/**
 * Derive sensible test defaults for a use case from its first active rule:
 * the object_type it matches and a confidence comfortably above its threshold.
 * Falls back to a generic detection when the use case has no rule yet.
 */
export function deriveTestDefaults(rules, useCaseId) {
  const ucRules = (rules || []).filter(r => r.use_case_id === useCaseId && r.active !== false)
  for (const rule of ucRules) {
    const conds = rule.conditions || []
    const objCond = conds.find(c => c.field === 'object_type' && (c.op === 'eq' || c.op === 'in'))
    const confCond = conds.find(c => c.field === 'confidence' && c.op === 'gte')
    const object = objCond ? (Array.isArray(objCond.value) ? objCond.value[0] : objCond.value) : null
    const minConf = confCond ? Number(confCond.value) : 60
    if (object) return { object_type: String(object), confidence: Math.min(99, minConf + 15) }
  }
  return { object_type: 'object', confidence: 85 }
}
