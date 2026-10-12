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


def _open_incident_event_ids(use_case_id: str, zone_id: str | None, same_zone: bool,
                              cutoff_iso: str) -> set:
    """Event ids already attached to a still-OPEN *and recently active*
    incident in scope.

    A lower-severity immediate rule (e.g. "single detection") consumes an
    event the moment it opens an incident with it — otherwise that same event
    could wrongly re-confirm ANOTHER fresh incident later (see the comment
    below). But that consumption must not also starve a higher-severity
    confirmation rule trying to escalate THAT SAME still-open incident: the
    event never left the story, the incident just hasn't closed yet. So an
    event consumed by a currently-open, recently-active incident stays
    eligible for confirmation counting; an event consumed by an incident that
    has since closed, been deleted, or simply gone stale (no activity within
    this same confirmation window — server.py's INCIDENT_MERGE_WINDOW_S
    treats it as a separate sighting too, by the same cutoff) is excluded.
    """
    incidents = [
        i for i in data_store.get_all("incidents")
        if i.get("use_case_id") == use_case_id
        and i.get("status") in ("ACTIVE", "OPERATOR_REVIEW")
        and (i.get("last_event_at") or i.get("opened_at") or "") >= cutoff_iso
    ]
    if same_zone and zone_id is not None:
        incidents = [i for i in incidents if i.get("zone_id") == zone_id]
    ids = set()
    for i in incidents:
        ids.update(i.get("event_ids") or [])
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

        # An event that already contributed to some incident is stamped
        # `consumed` at the time it was attached — see server.py's
        # _run_rule_engine(). That must not block a higher-severity
        # confirmation rule from counting an event still sitting in the SAME
        # open incident this detection is about to (re)join: only an event
        # consumed by an incident that has since closed (or been deleted,
        # which leaves no open-incident record to find) stays excluded.
        still_open_ids = _open_incident_event_ids(
            use_case_id, event.get("zone_id"), bool(confirmation.get("same_zone")), cutoff_iso
        )
        matching_past = [
            e for e in past
            if e.get("id") != event.get("id")
            and (not e.get("consumed") or e.get("id") in still_open_ids)
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
