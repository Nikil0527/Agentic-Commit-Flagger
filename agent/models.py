from datetime import datetime
from pydantic import BaseModel


class Alert(BaseModel):
    status: str
    labels: dict[str, str] = {}
    annotations: dict[str, str] = {}
    startsAt: datetime | None = None
    endsAt: datetime | None = None
    fingerprint: str = ""


class AlertmanagerWebhook(BaseModel):
    version: str = "4"
    groupKey: str
    status: str
    receiver: str = ""
    groupLabels: dict[str, str] = {}
    commonLabels: dict[str, str] = {}
    commonAnnotations: dict[str, str] = {}
    externalURL: str = ""
    alerts: list[Alert] = []
