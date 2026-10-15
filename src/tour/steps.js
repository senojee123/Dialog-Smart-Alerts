/**
 * Guided tour scripts. One elephant-crossing story, start to finish — a short
 * executive cut (default) and a full walkthrough for operators.
 *
 * step = {
 *   id, title, text            — caption + narration
 *   route?                     — navigate here first (omit to stay put)
 *   target?                    — [data-tour="…"] to spotlight (omit → centred card)
 *   action?(), actionAt?       — scripted live activity, fired once per tour run when
 *                                narrated sentence #actionAt starts (default 0)
 *   onEnter?()                 — runs every time the step is shown
 *   minMs?                     — keep the step on screen at least this long
 * }
 */

import { detect, moveTarget, resolveActive, latestActiveIncidentId } from './demoStore.js'

const LNG = 81.48

export const FULL_TOUR_STEPS = [
  {
    id: 'welcome', route: '/', title: 'Welcome to Dialog Smart Alerts',
    text: 'Welcome to Dialog Smart Alerts, a notification and alerting platform that turns sensor detections into instant, coordinated action. ' +
          'In this tour, I will walk you through a live elephant crossing on the B43 Yala road corridor, from the very first camera detection, all the way to the all-clear.',
  },
  {
    id: 'status', route: '/', target: 'topbar-status', title: 'Live system status',
    text: 'Up here, the live badge and the health indicator confirm that the platform is connected and processing in real time. ' +
          'The bell lets an operator switch the audible alert cue on or off.',
  },
  {
    id: 'nav', route: '/', target: 'nav', title: 'Everything in one place',
    text: 'The menu on the left is organised into Operations, for day-to-day monitoring, and Configuration, where detection rules, responders, cameras and road signs are set up. ' +
          'Bringing a new elephant corridor online is a matter of configuration, not new software.',
  },
  {
    id: 'kpis', route: '/', target: 'kpis', title: 'A detection comes in',
    text: 'These cards show the headline numbers for today. And right now, a camera on the B43 corridor has spotted an elephant near the road. ' +
          'Watch the active incidents counter. The detection was matched by a rule, and an incident opened automatically, in under a second.',
    action: () => detect({ deviceId: 'CAM-B43-02', confidence: 91 }),
    actionAt: 1,
  },
  {
    id: 'activity', route: '/', target: 'activity', title: 'The story, as it happens',
    text: 'The activity timeline tells the story as it unfolds: the camera detection, the AI confidence score, the incident being created, and the smart road signs being updated.',
  },
  {
    id: 'charts', route: '/', target: 'charts', title: 'Patterns over time',
    text: 'Detection statistics and the twenty-four hour trend help supervisors spot patterns, such as the evening peak, when elephants most often cross the road.',
  },
  {
    id: 'confirm', route: '/', target: 'recent-incidents', title: 'Confirmed and escalated',
    text: 'A second camera, further along the road, has now confirmed the sighting, this time with two elephants in view. ' +
          'Two detections in the same zone, within fifteen minutes, trigger the dual-confirmation rule, and the incident is escalated to critical.',
    action: () => detect({ deviceId: 'CAM-B43-03', confidence: 94, herd: 2 }),
    actionAt: 0,
  },
  {
    id: 'incidents', route: '/incidents', target: 'incident-table', title: 'Live Incidents',
    text: 'The Live Incidents view is the operator\'s main workspace. Critical incidents are pinned to the top, ' +
          'with severity, confidence, notification delivery, and hardware state, all updating live.',
  },
  {
    id: 'detail', route: '/incidents', target: 'incident-detail', title: 'The full picture',
    text: 'Opening the incident shows the full picture: the camera evidence, the confidence score, the rules that fired, ' +
          'and the roadside siren, which was switched on automatically when the incident became critical.',
    onEnter: () => window.dispatchEvent(new CustomEvent('tour:select-incident', { detail: latestActiveIncidentId() })),
  },
  {
    id: 'stakeholders', route: '/incidents', target: 'incident-stakeholders', title: 'The right people, instantly',
    text: 'Every stakeholder is notified on their preferred channels, such as SMS, WhatsApp, or email, and you can see each message being delivered and acknowledged. ' +
          'Here, the park warden has already responded, and is on the way.',
    onEnter: () => window.dispatchEvent(new CustomEvent('tour:select-incident', { detail: latestActiveIncidentId() })),
  },
  {
    id: 'audit', route: '/incidents', target: 'incident-timeline', title: 'A complete audit trail',
    text: 'And the timeline keeps a complete, time-stamped audit trail of every decision the system made, and every action that was taken.',
    onEnter: () => window.dispatchEvent(new CustomEvent('tour:select-incident', { detail: latestActiveIncidentId() })),
  },
  {
    id: 'signs', route: '/road-signs', target: 'sign-grid', title: 'Smart road signs',
    text: 'These are the smart LED road signs along the corridor. Boards close to a detection light up red, warning drivers to slow down. ' +
          'As the herd moves north, watch the warning travel along with them. Boards they have passed fade to amber, and then back to green once the road is clear. ' +
          'No manual action is needed.',
    action: () => moveTarget([[6.3803, LNG], [6.3846, LNG]], { steps: 8, stepMs: 2600, confidence: 86, herd: 2 }),
    actionAt: 1,
    minMs: 26000,
  },
  {
    id: 'sign-summary', route: '/road-signs', target: 'sign-summary', title: 'Board status at a glance',
    text: 'The summary chips give an instant count of boards in warning, caution, clear, or offline, and a map view shows exactly where each board stands.',
  },
  {
    id: 'map', route: '/map', target: 'main', title: 'Map view',
    text: 'The map view plots every incident geographically, so the operations centre can see activity across the Yala corridor, the Southern Highway, and Kataragama Road, at a glance.',
  },
  {
    id: 'devices', route: '/devices', target: 'device-table', title: 'Connected devices',
    text: 'Every camera, thermal sensor, and acoustic array reports a regular heartbeat, so you always know which devices are online. ' +
          'Each device authenticates with its own key, and any camera or AI service can plug in through the same standard interface.',
  },
  {
    id: 'rules', route: '/admin/rules', target: 'main', title: 'Rules engine',
    text: 'The rules engine is where behaviour is defined, with no code required. ' +
          'Here, a single detection raises a high alert, while two confirmed detections escalate to critical, and notify every responder.',
  },
  {
    id: 'people', route: '/admin/stakeholders', target: 'main', title: 'Stakeholders',
    text: 'Stakeholders are managed centrally: wildlife officers, traffic control, the police, and the operations centre, each with their own channels and on-call status.',
  },
  {
    id: 'wizard', target: 'nav-setup', title: 'New corridors in minutes',
    text: 'And to protect a new stretch of road, the Setup Wizard guides you through five simple steps: choose the corridor, place cameras and signs on the map, define the response, then review, and run a test.',
  },
  {
    id: 'resolve', route: '/', target: 'recent-incidents', title: 'All clear',
    text: 'Back on the dashboard. Once no further detections arrive, the incident is resolved automatically, the signs return to road clear, and an all-clear message goes out to everyone involved.',
    action: () => resolveActive(),
    actionAt: 1,
  },
  {
    id: 'finish', route: '/', title: 'Detect. Decide. Notify. Warn.',
    text: 'That is Dialog Smart Alerts: detect, decide, notify, and warn, automatically, in seconds. ' +
          'Thank you for taking the tour. You can replay it at any time from the Help section of the menu.',
  },
]

const openLatestIncident = () =>
  window.dispatchEvent(new CustomEvent('tour:select-incident', { detail: latestActiveIncidentId() }))

/** Executive cut — outcomes over mechanics, ~2–2½ minutes. */
export const EXEC_TOUR_STEPS = [
  {
    id: 'welcome', route: '/', title: 'Welcome to Dialog Smart Alerts',
    text: 'Dialog Smart Alerts turns a single camera detection into coordinated action, in seconds. ' +
          'Let me show you a live elephant crossing on the B43 Yala corridor.',
  },
  {
    id: 'kpis', route: '/', target: 'kpis', title: 'A detection comes in',
    text: 'A roadside camera has just spotted an elephant. ' +
          'Within a second, an incident is opened automatically. Nobody had to press a button.',
    action: () => detect({ deviceId: 'CAM-B43-02', confidence: 91 }),
    actionAt: 1,
  },
  {
    id: 'confirm', route: '/', target: 'recent-incidents', title: 'Confirmed and escalated',
    text: 'A second camera confirms it: two elephants. The system escalates to critical, on its own.',
    action: () => detect({ deviceId: 'CAM-B43-03', confidence: 94, herd: 2 }),
    actionAt: 0,
  },
  {
    id: 'detail', route: '/incidents', target: 'incident-detail', title: 'The right people, instantly',
    text: 'Operators see the camera evidence, and every responder, from wildlife officers to the police and traffic control, is alerted by SMS and WhatsApp. ' +
          'The park warden is already on the way.',
    onEnter: openLatestIncident,
  },
  {
    id: 'signs', route: '/road-signs', target: 'sign-grid', title: 'Drivers are warned too',
    text: 'Drivers are warned too. Signs near the herd turn red, and the warning follows the elephants as they move.',
    action: () => moveTarget([[6.3803, LNG], [6.3846, LNG]], { steps: 7, stepMs: 2000, confidence: 86, herd: 2 }),
    actionAt: 0,
    minMs: 18000,
  },
  {
    id: 'platform', route: '/admin/rules', target: 'main', title: 'Configured, not coded',
    text: 'All of this is configured, not coded. ' +
          'Detection rules, responders, and road signs are set up in a few clicks, and a new elephant corridor goes live through a simple setup wizard.',
  },
  {
    id: 'resolve', route: '/', target: 'recent-incidents', title: 'All clear',
    text: 'When the danger passes, the incident resolves itself, and everyone gets the all-clear.',
    action: () => resolveActive(),
    actionAt: 0,
  },
  {
    id: 'finish', route: '/', title: 'Detect. Decide. Notify. Warn.',
    text: 'Detect, decide, notify, and warn: automatically, in seconds, around the clock.',
  },
]

export const TOURS = {
  executive: { label: 'Executive Tour', steps: EXEC_TOUR_STEPS, hints: false },
  full:      { label: 'Full Tour',      steps: FULL_TOUR_STEPS, hints: true },
}
