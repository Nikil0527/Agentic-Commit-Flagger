import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from agent.models import AlertmanagerWebhook

log = logging.getLogger("agent")

# anchored to the repo instead of the cwd so a restart from a different directory
# does not silently start a second incident store
DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "incidents"


class IncidentStore:
    """One incident per alertmanager groupKey. Every pipeline step gets appended
    to the incident's event log on disk - the postmortem generator reads these later."""

    def __init__(self, data_dir: Path = DEFAULT_DATA_DIR):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        # maps groupKey to the incident id and its first alert start time
        self.open_incidents: dict[str, dict] = {}
        self._reload()

    def record(self, payload: AlertmanagerWebhook) -> str | None:
        """Returns the incident id, or None when the notification is a no-op."""
        existing = self.open_incidents.get(payload.groupKey)
        starts_at = self._max_starts_at(payload)

        if payload.status == "firing":
            if existing:
                self._append(existing["id"], "refire", self._alert_summary(payload), payload.groupKey)
                return existing["id"]
            incident_id = f"inc-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
            data = self._alert_summary(payload)
            data["alert_starts_at"] = starts_at
            # write first and index second so a failed write cannot leave a phantom entry
            # that the alertmanager retry would turn into a headerless incident file
            self._append(incident_id, "alert_received", data, payload.groupKey)
            self.open_incidents[payload.groupKey] = {"id": incident_id, "alert_starts_at": starts_at}
            return incident_id

        if payload.status == "resolved" and existing:
            # a late duplicate resolved from a previous flap must not close the new incident
            if starts_at and existing["alert_starts_at"] and starts_at < existing["alert_starts_at"]:
                self._append(existing["id"], "stale_resolved_ignored", self._alert_summary(payload), payload.groupKey)
                return None
            self._append(existing["id"], "resolved", self._alert_summary(payload), payload.groupKey)
            del self.open_incidents[payload.groupKey]
            return existing["id"]

        return None

    def log_step(self, incident_id: str, event: str, data: dict, group_key: str = ""):
        self._append(incident_id, event, data, group_key)

    def summary(self) -> list[dict]:
        out = []
        for f in sorted(self.data_dir.glob("*.jsonl")):
            events = self._read_events(f)
            if not events:
                continue
            first = events[0]
            out.append({
                "id": f.stem,
                "status": "resolved" if any(e.get("event") == "resolved" for e in events) else "open",
                "alertname": first.get("data", {}).get("alertname", ""),
                "started": first.get("ts", ""),
                "events": len(events),
            })
        return out

    def _reload(self):
        # rebuild the open incident index from disk so a restart does not lose track
        for f in sorted(self.data_dir.glob("*.jsonl")):
            events = self._read_events(f)
            if not events:
                continue
            group_key = next((e["group_key"] for e in events if e.get("group_key")), "")
            if not group_key or any(e.get("event") == "resolved" for e in events):
                continue
            received = next((e for e in events if e.get("event") == "alert_received"), {})
            self.open_incidents[group_key] = {
                "id": f.stem,
                "alert_starts_at": received.get("data", {}).get("alert_starts_at"),
            }

    def _read_events(self, path: Path) -> list[dict]:
        events = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                # a torn line from a crash during a write must not brick the whole store
                log.warning("skipping corrupt line in %s", path.name)
        return events

    def _max_starts_at(self, payload: AlertmanagerWebhook) -> str | None:
        stamps = [a.startsAt for a in payload.alerts if a.startsAt]
        return max(stamps).isoformat() if stamps else None

    def _alert_summary(self, payload: AlertmanagerWebhook) -> dict:
        return {
            "alertname": payload.groupLabels.get("alertname", ""),
            "labels": payload.commonLabels,
            "annotations": payload.commonAnnotations,
            "alert_count": len(payload.alerts),
        }

    def _append(self, incident_id: str, event: str, data: dict, group_key: str = ""):
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "event": event,
            "group_key": group_key,
            "data": data,
        }
        path = self.data_dir / f"{incident_id}.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
