"""
Notification dispatcher — simulates SMS, WhatsApp, Email.
All sends are logged to notifications.json for the dashboard to display.
"""

import uuid
from datetime import datetime, timezone
import data_store


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _render(template: str, ctx: dict) -> str:
    try:
        return template.format(**ctx)
    except KeyError:
        return template


def _build_context(incident: dict, event: dict) -> dict:
    zone = data_store.get_by_id("zones", event.get("zone_id", "")) or {}
    device = data_store.get_by_id("devices", event.get("device_id", "")) or {}
    return {
        "incident_id":  incident.get("id", ""),
        "zone_name":    zone.get("name", event.get("zone_id", "Unknown Zone")),
        "device_name":  device.get("name", event.get("device_id", "Unknown Device")),
        "object_type":  event.get("object_type", "object"),
        "confidence":   round(float(event.get("confidence", 0))),
        "severity":     incident.get("severity", ""),
        "road":         zone.get("road", ""),
    }


def dispatch(incident: dict, rule: dict, action_key: str, event: dict) -> list[dict]:
    """
    Fires notifications for the given action_key ('on_trigger' or 'on_confirm').
    Falls back to 'on_trigger' actions when 'on_confirm' block is absent.
    Returns list of notification records saved to data store.
    """
    actions = rule.get("actions", {})
    action_block = actions.get(action_key) or actions.get("on_trigger", {})
    if not action_block:
        return []

    stakeholder_ids = action_block.get("notify_stakeholder_ids", [])
    template = action_block.get(
        "message_template",
        "Alert [{severity}]: {object_type} detected in {zone_name} by {device_name}. "
        "Confidence: {confidence}%. Incident: {incident_id}"
    )
    ctx = _build_context(incident, event)
    message = _render(template, ctx)

    saved = []
    for sh_id in stakeholder_ids:
        stakeholder = data_store.get_by_id("stakeholders", sh_id)
        if not stakeholder:
            continue
        for channel in stakeholder.get("channels", []):
            ch_type = channel.get("type", "sms")
            address = channel.get("address", "")
            if not address:
                continue

            record = {
                "id":               f"NOTIF-{uuid.uuid4().hex[:8].upper()}",
                "incident_id":      incident.get("id"),
                "event_id":         event.get("id"),
                "stakeholder_id":   sh_id,
                "stakeholder_name": stakeholder.get("name", ""),
                "channel":          ch_type,
                "address":          address,
                "message":          message,
                "status":           "simulated",
                "sent_at":          _now(),
            }
            data_store.create("notifications", record)
            saved.append(record)

            tag = ch_type.upper()
            print(f"  [{tag}] → {address}: {message}")

    return saved


def actuate_signs(rule: dict, action_key: str) -> list[str]:
    """
    Updates road sign states as specified in rule actions.
    Returns list of sign IDs that were actuated.
    """
    actions = rule.get("actions", {})
    action_block = actions.get(action_key) or actions.get("on_trigger", {})
    sign_ids = action_block.get("actuate_sign_ids", [])
    new_state = action_block.get("sign_state", "WARNING")

    actuated = []
    for sid in sign_ids:
        result = data_store.update("road_signs", sid, {"forced_state": new_state})
        if result:
            actuated.append(sid)
            print(f"  [SIGN] {sid} → {new_state}")
    return actuated
