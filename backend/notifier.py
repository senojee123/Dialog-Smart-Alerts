"""
Notification dispatcher — simulates SMS, WhatsApp, Email.
All sends are logged to notifications for the dashboard to display.

Stage B1: async, backed by repo. (Stage B5 will move this to a persisted
outbox + dispatcher worker with real retries/delivery states.)
"""

import uuid
from datetime import datetime, timezone
import repo


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _render(template: str, ctx: dict) -> str:
    try:
        return template.format(**ctx)
    except KeyError:
        return template


async def _build_context(incident: dict, event: dict) -> dict:
    zone = await repo.get_by_id("zones", event.get("zone_id", "")) or {}
    device = await repo.get_by_id("devices", event.get("device_id", "")) or {}
    return {
        "incident_id":  incident.get("id", ""),
        "zone_name":    zone.get("name", event.get("zone_id", "Unknown Zone")),
        "device_name":  device.get("name", event.get("device_id", "Unknown Device")),
        "object_type":  event.get("object_type", "object"),
        "confidence":   round(float(event.get("confidence", 0))),
        "severity":     incident.get("severity", ""),
        "road":         zone.get("road", ""),
    }


async def dispatch(incident: dict, rule: dict, action_key: str, event: dict) -> list[dict]:
    """
    Fires notifications for the given action_key ('on_trigger' or 'on_confirm').
    Falls back to 'on_trigger' actions when 'on_confirm' block is absent.
    Returns list of notification records saved to the store.
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
    ctx = await _build_context(incident, event)
    message = _render(template, ctx)

    saved = []
    for sh_id in stakeholder_ids:
        stakeholder = await repo.get_by_id("stakeholders", sh_id)
        if not stakeholder:
            continue
        for channel in stakeholder.get("channels", []):
            ch_type = channel.get("type", "sms")
            address = channel.get("address", "")
            if not address:
                continue

            status = "simulated"
            if ch_type == "sms":
                import os
                import json
                import urllib.request
                import asyncio
                
                # Fetch credentials (defaulting to your production credentials)
                api_url = os.environ.get("IDEABIZ_API_URL", "https://ideabiz.lk/apicall/smsmessaging/v3/outbound/87798/requests")
                api_token = os.environ.get("IDEABIZ_TOKEN", "aec2bd31-f3ba-38e0-a4ae-3785b6af1638")
                sender_port = os.environ.get("IDEABIZ_SENDER_PORT", "tel:87798")
                sender_name = os.environ.get("IDEABIZ_SENDER_NAME", "smartalerts")
                
                # Normalize to tel:+94... format required by Ideabiz
                clean_num = "".join(c for c in address if c.isdigit() or c == "+")
                if clean_num.startswith("+"):
                    recipient_num = f"tel:{clean_num}"
                elif clean_num.startswith("94"):
                    recipient_num = f"tel:+{clean_num}"
                elif clean_num.startswith("0"):
                    recipient_num = f"tel:+94{clean_num[1:]}"
                else:
                    recipient_num = f"tel:+94{clean_num}"
                
                payload = {
                    "outboundSMSMessageRequest": {
                        "address": [recipient_num],
                        "senderAddress": sender_port,
                        "outboundSMSTextMessage": {
                            "message": message
                        },
                        "clientCorrelator": incident.get("id", "123456"),
                        "senderName": sender_name
                    }
                }
                
                def _post_sms(url, token, body_dict):
                    req = urllib.request.Request(
                        url,
                        data=json.dumps(body_dict).encode("utf-8"),
                        headers={
                            "Content-Type": "application/json",
                            "Accept": "application/json",
                            "Authorization": f"Bearer {token}"
                        },
                        method="POST"
                    )
                    with urllib.request.urlopen(req, timeout=5) as response:
                        return json.loads(response.read().decode("utf-8"))
                
                try:
                    # Run blocking network call in thread executor to keep FastAPI responsive
                    res_data = await asyncio.to_thread(_post_sms, api_url, api_token, payload)
                    if "serverReferenceCode" in res_data.get("outboundSMSMessageRequest", {}):
                        status = "sent"
                        print(f"  [SMS] → {address}: Successfully sent via Ideabiz (Ref: {res_data['outboundSMSMessageRequest']['serverReferenceCode']})")
                    else:
                        status = "failed"
                        print(f"  [SMS] → {address}: Failed to send via Ideabiz (Response: {res_data})")
                except Exception as e:
                    status = "failed"
                    print(f"  [SMS] → {address}: Error dispatching via Ideabiz API: {e}")
            else:
                print(f"  [{ch_type.upper()}] (SIMULATED) → {address}: {message}")

            record = await repo.create("notifications", {
                "id":               f"NOTIF-{uuid.uuid4().hex[:8].upper()}",
                "incident_id":      incident.get("id"),
                "event_id":         event.get("id"),
                "stakeholder_id":   sh_id,
                "stakeholder_name": stakeholder.get("name", ""),
                "channel":          ch_type,
                "address":          address,
                "message":          message,
                "status":           status,
                "sent_at":          _now(),
            })
            saved.append(record)

    return saved

