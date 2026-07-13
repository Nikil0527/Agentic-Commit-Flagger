import logging
from pathlib import Path

import truststore

# use the OS cert store - av tools intercept https and python's bundled CAs reject them
truststore.inject_into_ssl()

from fastapi import BackgroundTasks, FastAPI

from agent.github_client import GitHubClient
from agent.incidents import IncidentStore
from agent.models import AlertmanagerWebhook

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("agent")


def create_app(data_dir: Path | None = None, github: GitHubClient | None = None) -> FastAPI:
    app = FastAPI(title="commit-flagger-agent")
    store = IncidentStore(data_dir) if data_dir else IncidentStore()
    gh = github or GitHubClient()
    app.state.store = store

    async def investigate(incident_id: str, group_key: str):
        try:
            commits = await gh.recent_commits()
            store.log_step(incident_id, "commits_fetched", {"repo": gh.repo, "commits": commits}, group_key)
            log.info("[%s] fetched %d recent commits from %s", incident_id, len(commits), gh.repo)
        except Exception as e:
            # the incident log still has the alert even if github is down
            store.log_step(incident_id, "commits_fetch_failed", {"error": str(e)}, group_key)
            log.error("[%s] commit fetch failed: %s", incident_id, e)

    @app.post("/webhook/alertmanager")
    async def alertmanager_webhook(payload: AlertmanagerWebhook, background: BackgroundTasks):
        # respond fast - alertmanager retries anything that isn't a quick 2xx
        was_open = payload.groupKey in store.open_incidents
        incident_id = store.record(payload)
        if incident_id:
            log.info("[%s] %s: %s", incident_id, payload.status, payload.groupLabels.get("alertname", "?"))
        else:
            log.warning("no-op %s notification for group %s", payload.status, payload.groupKey)

        if incident_id and payload.status == "firing" and not was_open:
            background.add_task(investigate, incident_id, payload.groupKey)
        return {"incident": incident_id, "status": payload.status}

    @app.get("/incidents")
    def incidents():
        return store.summary()

    @app.get("/health")
    def health():
        return {"ok": True}

    return app


app = create_app()
