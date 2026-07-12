import logging
from pathlib import Path

from fastapi import FastAPI

from agent.incidents import IncidentStore
from agent.models import AlertmanagerWebhook

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("agent")


def create_app(data_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="commit-flagger-agent")
    store = IncidentStore(data_dir) if data_dir else IncidentStore()
    app.state.store = store

    @app.post("/webhook/alertmanager")
    async def alertmanager_webhook(payload: AlertmanagerWebhook):
        # respond fast - alertmanager retries anything that isn't a quick 2xx
        incident_id = store.record(payload)
        if incident_id:
            log.info("[%s] %s: %s", incident_id, payload.status, payload.groupLabels.get("alertname", "?"))
        else:
            # dropped notifications still deserve a trace in the logs
            log.warning("no-op %s notification for group %s", payload.status, payload.groupKey)
        return {"incident": incident_id, "status": payload.status}

    @app.get("/incidents")
    def incidents():
        return store.summary()

    @app.get("/health")
    def health():
        return {"ok": True}

    return app


app = create_app()
