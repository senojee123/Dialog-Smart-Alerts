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
    Evaluate the event against all active rules for its use case and return the
    single best (rule, action_key) to act on.

    Selection precedence (so a pending confirmation rule never blocks an
    immediate rule):
      1. Highest-priority rule whose confirmation threshold is now met → on_confirm
      2. Else highest-priority immediate rule (no confirmation block)   → on_trigger
      3. Else highest-priority rule still awaiting confirmation         → pending
      4. Else                                                           → (None, None)
    """
    use_case_id = event.get("use_case_id")
    if not use_case_id:
        return None, None

    rules = [
        r for r in data_store.get_all("rules")
        if r.get("use_case_id") == use_case_id
        and r.get("active", True)
    ]
    rules.sort(key=lambda r: -int(r.get("priority", 0)))  # highest priority first

    now = _parse_dt(event.get("received_at")) or datetime.now(timezone.utc)
    all_events = data_store.get_all("detection_events")

    confirmed, immediate, pending = [], [], []

    for rule in rules:
        if not _matches_conditions(event, rule.get("conditions", [])):
            continue

        confirmation = rule.get("confirmation")
        if not confirmation:
            immediate.append(rule)
            continue

        window_s = int(confirmation.get("window_seconds", 900))
        cutoff   = now - timedelta(seconds=window_s)
        matching_past = [
            e for e in all_events
            if e.get("id") != event.get("id")
            and _parse_dt(e.get("received_at")) >= cutoff
            and e.get("use_case_id") == use_case_id
            and _matches_conditions(e, rule.get("conditions", []))
            and (not confirmation.get("same_zone")
                 or e.get("zone_id") == event.get("zone_id"))
        ]
        required = int(confirmation.get("required_count", 2))
        if len(matching_past) + 1 >= required:   # current event counts as 1
            confirmed.append(rule)
        else:
            pending.append(rule)

    if confirmed:
        return confirmed[0], "on_confirm"
    if immediate:
        return immediate[0], "on_trigger"
    if pending:
        return pending[0], "pending"
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
