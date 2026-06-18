"""
Rule evaluator: given a new detection event, find the best matching rule
and return (rule, action_key) where action_key is 'on_trigger' or 'on_confirm'.

Returns (None, None) if no rule matches.
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


def evaluate_event(event: dict) -> tuple[dict | None, str | None]:
    """
    Returns (rule, action_key) or (None, None).
    action_key: 'on_trigger' | 'on_confirm'
    """
    use_case_id = event.get("use_case_id")
    if not use_case_id:
        return None, None

    rules = [
        r for r in data_store.get_all("rules")
        if r.get("use_case_id") == use_case_id
        and r.get("active", True)
    ]
    # Higher priority number checked first
    rules.sort(key=lambda r: -int(r.get("priority", 0)))

    now = datetime.fromisoformat(event.get("received_at", datetime.now(timezone.utc).isoformat()))
    all_events = data_store.get_all("detection_events")

    for rule in rules:
        conditions = rule.get("conditions", [])
        if not _matches_conditions(event, conditions):
            continue

        confirmation = rule.get("confirmation")

        if not confirmation:
            return rule, "on_trigger"

        # Confirmation required: count recent matching events
        window_s = int(confirmation.get("window_seconds", 900))
        cutoff = now - timedelta(seconds=window_s)

        matching_past = [
            e for e in all_events
            if e.get("id") != event.get("id")
            and _parse_dt(e.get("received_at")) >= cutoff
            and _matches_conditions(e, conditions)
            and e.get("use_case_id") == use_case_id
            and (
                not confirmation.get("same_zone")
                or e.get("zone_id") == event.get("zone_id")
            )
        ]

        required = int(confirmation.get("required_count", 2))
        # Current event counts as 1, plus past matching events
        if len(matching_past) + 1 >= required:
            return rule, "on_confirm"
        else:
            # Conditions matched but confirmation not yet met — still useful
            # to return rule so caller can create a pending/watch incident
            return rule, "pending"

    return None, None


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
