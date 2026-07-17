def build_brief(alert: dict, ranking: dict, repo: str) -> str:
    """Turns a finished diagnosis into the short text a responder actually reads."""
    name = alert.get("alertname", "unknown alert")
    labels = alert.get("labels", {})
    summary = alert.get("annotations", {}).get("summary", "")

    lines = [f"INCIDENT: {name}"]
    if summary:
        lines.append(summary)
    target = labels.get("job") or labels.get("pod") or ""
    if target:
        lines.append(f"affected: {target}")
    lines.append("")

    suspects = ranking.get("suspects", [])
    if suspects:
        lines.append("suspect commits:")
        for i, s in enumerate(suspects, 1):
            lines.append(f"  {i}. {s.get('sha', '?')} [{s.get('confidence', '?')}] {s.get('reasoning', '')}")
        top = suspects[0].get("sha", "")
        if top:
            lines.append(f"  https://github.com/{repo}/commit/{top}")
    else:
        lines.append("no commit stands out as the cause, check config and infra changes by hand")

    assessment = ranking.get("assessment", "")
    if assessment:
        lines.append("")
        lines.append(f"assessment: {assessment}")
    return "\n".join(lines)
