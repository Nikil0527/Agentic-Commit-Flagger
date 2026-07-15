import logging
import os
from pathlib import Path

import truststore

# use the OS cert store because antivirus tools intercept https and the bundled certs reject them
truststore.inject_into_ssl()

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI

load_dotenv()

from agent.diagnosis import CulpritRanker
from agent.github_client import GitHubClient
from agent.incidents import IncidentStore
from agent.models import AlertmanagerWebhook

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("agent")

# how many newest commits get their full diff sent to the llm
DIFF_FETCH_LIMIT = 8


def create_app(
    data_dir: Path | None = None,
    github: GitHubClient | None = None,
    ranker: CulpritRanker | None | str = "auto",
) -> FastAPI:
    app = FastAPI(title="commit-flagger-agent")
    store = IncidentStore(data_dir) if data_dir else IncidentStore()
    gh = github or GitHubClient()
    if ranker == "auto":
        ranker = CulpritRanker() if os.environ.get("LLM_API_KEY") else None
    app.state.store = store

    async def investigate(incident_id: str, group_key: str, alert: dict):
        try:
            commits = await gh.recent_commits()
            store.log_step(incident_id, "commits_fetched", {"repo": gh.repo, "commits": commits}, group_key)
            log.info("[%s] fetched %d recent commits from %s", incident_id, len(commits), gh.repo)
        except Exception as e:
            # the incident log still has the alert even if github is down
            store.log_step(incident_id, "commits_fetch_failed", {"error": str(e)}, group_key)
            log.error("[%s] commit fetch failed: %s", incident_id, e)
            return

        if ranker is None:
            store.log_step(incident_id, "ranking_skipped", {"reason": "no llm api key"}, group_key)
            return

        try:
            diffs = {}
            for c in commits[:DIFF_FETCH_LIMIT]:
                diffs[c["sha"]] = await gh.commit_diff(c["sha"], max_chars=3000)
            result = await ranker.rank(alert, commits, diffs)
            store.log_step(incident_id, "culprits_ranked", result, group_key)
            top = result["suspects"][0]["sha"] if result.get("suspects") else "none"
            log.info("[%s] culprit ranking done, top suspect: %s", incident_id, top)
        except Exception as e:
            store.log_step(incident_id, "ranking_failed", {"error": str(e)}, group_key)
            log.error("[%s] ranking failed: %s", incident_id, e)

    @app.post("/webhook/alertmanager")
    async def alertmanager_webhook(payload: AlertmanagerWebhook, background: BackgroundTasks):
        # respond fast since alertmanager retries anything that is not a quick 2xx
        was_open = payload.groupKey in store.open_incidents
        incident_id = store.record(payload)
        if incident_id:
            log.info("[%s] %s: %s", incident_id, payload.status, payload.groupLabels.get("alertname", "?"))
        else:
            log.warning("no-op %s notification for group %s", payload.status, payload.groupKey)

        if incident_id and payload.status == "firing" and not was_open:
            alert = {
                "alertname": payload.groupLabels.get("alertname", ""),
                "labels": payload.commonLabels,
                "annotations": payload.commonAnnotations,
            }
            background.add_task(investigate, incident_id, payload.groupKey, alert)
        return {"incident": incident_id, "status": payload.status}

    @app.get("/incidents")
    def incidents():
        return store.summary()

    @app.get("/health")
    def health():
        return {"ok": True}

    return app


app = create_app()
