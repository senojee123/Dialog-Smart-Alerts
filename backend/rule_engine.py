"""
Rule evaluator: given a new detection event, find the best matching rule
and return (rule, action_key) where action_key is 'on_trigger' or 'on_confirm'.

Returns (None, None) if no rule matches.

Stage B1: queries are bounded/indexed via the JSON data_store, which is the
single source of truth for all runtime data (events, incidents, rules).
"""

from datetime import datetime, timedelta, timezone
import data_store


def _matches_conditions(event: dict, conditions: list) -> bool:
    for cond in conditions:
        field = cond.get("field")
        op = cond.get("op")
        value = cond.get("value")
        ev_val = event.get(field)

        if ev_val is None:
            return False

        if op == "eq":
            if str(ev_val).lower() != str(value).lower():
                return False
        elif op == "neq":
            if str(ev_val).lower() == str(value).lower():
                return False
        elif op == "gte":
            try:
                if float(ev_val) < float(value):
                    return False
            except (TypeError, ValueError):
                return False
        elif op == "lte":
            try:
                if float(ev_val) > float(value):
                    return False
            except (TypeError, ValueError):
                return False
        elif op == "in":
            if ev_val not in (value if isinstance(value, list) else [value]):
                return False
        elif op == "contains":
            if str(value).lower() not in str(ev_val).lower():
                return False

    return True


# ── data_store-backed query helpers (replaces SQLite repo calls) ──────────────

def _active_rules_for(use_case_id: str) -> list[dict]:
    """All active rules for a use case, sorted by priority descending."""
    rules = [
        r for r in data_store.get_all("rules")
        if r.get("use_case_id") == use_case_id and r.get("active", True)
    ]
    return sorted(rules, key=lambda r: r.get("priority", 0), reverse=True)


def _recent_matching_events(use_case_id: str, zone_id: str | None,
                             cutoff_iso: str, same_zone: bool) -> list[dict]:
    """Events for a use case since cutoff_iso (for rule-confirmation windows)."""
    events = [
        e for e in data_store.get_all("detection_events")
        if e.get("use_case_id") == use_case_id
        and (e.get("received_at") or "") >= cutoff_iso
    ]
    if same_zone and zone_id is not None:
        events = [e for e in events if e.get("zone_id") == zone_id]
    return events


def _closed_incident_event_ids(cutoff_iso: str) -> set[str]:
    """Event IDs consumed by closed incidents or explicitly marked consumed."""
    ids: set[str] = set()
    for e in data_store.get_all("detection_events"):
        if e.get("consumed"):
            ids.add(e.get("id"))
    for inc in data_store.get_all("incidents"):
        if inc.get("status") in ("CLOSED", "RESOLVED"):
            ids.update(inc.get("event_ids") or [])
    return ids


# ── main evaluator ────────────────────────────────────────────────────────────

async def evaluate_event(event: dict) -> tuple[dict | None, str | None]:
    """
    Evaluate the event against all active rules for its use case and return the
    single best (rule, action_key) to act on.

    Precedence: confirmed (threshold met) > immediate > pending > none.
    """
    use_case_id = event.get("use_case_id")
    if not use_case_id:
        return None, None

    rules = _active_rules_for(use_case_id)  # priority descending
    now = _parse_dt(event.get("received_at")) or datetime.now(timezone.utc)

    confirmed, immediate, pending = [], [], []

    for rule in rules:
        if not _matches_conditions(event, rule.get("conditions", [])):
            continue

        confirmation = rule.get("confirmation")
        if not confirmation:
            immediate.append(rule)
            continue

        window_s = int(confirmation.get("window_seconds", 900))
        cutoff_iso = (now - timedelta(seconds=window_s)).isoformat()

        # All events in the window for this use case / zone
        past = _recent_matching_events(
            use_case_id, event.get("zone_id"), cutoff_iso,
            bool(confirmation.get("same_zone"))
        )
        # Events already consumed by a closed/resolved incident don't re-confirm
        consumed = _closed_incident_event_ids(cutoff_iso)

        matching_past = [
            e for e in past
            if e.get("id") != event.get("id")
            and e.get("id") not in consumed
            and _matches_conditions(e, rule.get("conditions", []))
        ]
        required = int(confirmation.get("required_count", 2))
        past_ids = [e.get("id") for e in matching_past]
        if len(matching_past) + 1 >= required:   # current event counts as 1
            confirmed.append((rule, past_ids))
        else:
            pending.append((rule, past_ids))

    if confirmed:
        return confirmed[0][0], "on_confirm", confirmed[0][1]
    if immediate:
        return immediate[0], "on_trigger", []
    if pending:
        return pending[0][0], "pending", pending[0][1]
    return None, None, []


def _parse_dt(s) -> datetime:
    if not s:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(s))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)
