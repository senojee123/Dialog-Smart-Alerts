"""
Notification dispatcher — simulates SMS, WhatsApp, Email, and connects to Ideabiz SMS API.
All sends are logged to notifications for the dashboard to display.

Stage B1: backed by data_store (JSON files) to ensure full consistency with the UI.
"""

import uuid
import os
import json
import urllib.request
import asyncio
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


def _post_sms(url, token, recipient_num, sender_port, sender_name, message, client_correlator):
    payload = {
        "outboundSMSMessageRequest": {
            "address": [recipient_num],
            "senderAddress": sender_port,
            "outboundSMSTextMessage": {
                "message": message
            },
            "senderName": sender_name
        }
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        },
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


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

            status = "simulated"
            if ch_type == "sms":
                # Fetch credentials (defaulting to your production credentials)
                api_url = os.environ.get("IDEABIZ_API_URL", "https://ideabiz.lk/apicall/smsmessaging/v3/outbound/87798/requests")
                api_token = os.environ.get("IDEABIZ_TOKEN", "aec2bd31-f3ba-38e0-a4ae-3785b6af1638")
                sender_port = os.environ.get("IDEABIZ_SENDER_PORT", "tel:87798")
                sender_name = os.environ.get("IDEABIZ_SENDER_NAME", "smartalerts")
                
                # Diagnostic printing to verify environment variable configuration
                print(f"  [SMS Debug] Using URL: {api_url} | Port: {sender_port} | Token: ...{api_token[-5:]}")
                
                # Normalize to tel:94... format required by Ideabiz (no '+' sign)
                clean_num = "".join(c for c in address if c.isdigit())
                if clean_num.startswith("94"):
                    recipient_num = f"tel:{clean_num}"
                elif clean_num.startswith("0"):
                    recipient_num = f"tel:94{clean_num[1:]}"
                else:
                    recipient_num = f"tel:94{clean_num}"
                
                # Send the exact rendered message template as configured in the Rule Engine.
                sms_body = message
                
                try:
                    # Run blocking network call in thread executor with isolated parameters to prevent race conditions
                    res_data = await asyncio.to_thread(
                        _post_sms, 
                        api_url, 
                        api_token, 
                        recipient_num, 
                        sender_port, 
                        sender_name, 
                        sms_body, 
                        incident.get("id", "123456")
                    )
                    if "serverReferenceCode" in res_data.get("outboundSMSMessageRequest", {}):
                        status = "sent"
                        print(f"  [SMS] → {address}: Successfully sent via Ideabiz (Ref: {res_data['outboundSMSMessageRequest']['serverReferenceCode']})")
                    else:
                        status = f"failed: {res_data}"
                        print(f"  [SMS] → {address}: Failed to send via Ideabiz (Response: {res_data})")
                except Exception as e:
                    err_msg = str(e)
                    if hasattr(e, 'read'):
                        try:
                            err_msg += f" - Response: {e.read().decode('utf-8')}"
                        except Exception:
                            pass
                    status = f"failed: {err_msg}"
                    print(f"  [SMS] → {address}: Error dispatching via Ideabiz API: {err_msg}")
            else:
                print(f"  [{ch_type.upper()}] (SIMULATED) → {address}: {message}")

            record = data_store.create("notifications", {
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
