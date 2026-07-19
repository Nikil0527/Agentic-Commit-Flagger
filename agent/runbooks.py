import re
from collections import Counter
from pathlib import Path

DEFAULT_RUNBOOK_DIR = Path(__file__).resolve().parent.parent / "runbooks"


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


class RunbookIndex:
    """Matches incidents to runbooks with tf idf scoring, seven docs need no vector db."""

    def __init__(self, runbook_dir: Path | None = None):
        self.dir = Path(runbook_dir) if runbook_dir else DEFAULT_RUNBOOK_DIR
        self.docs: dict[str, str] = {}
        self.counts: dict[str, Counter] = {}
        self.lengths: dict[str, int] = {}
        if self.dir.exists():
            for f in sorted(self.dir.glob("*.md")):
                text = f.read_text(encoding="utf-8")
                toks = _tokens(text)
                self.docs[f.name] = text
                self.counts[f.name] = Counter(toks)
                self.lengths[f.name] = max(len(toks), 1)

    def match(self, query: str) -> dict | None:
        if not self.docs:
            return None
        words = set(_tokens(query))
        scores = {}
        for name, counts in self.counts.items():
            # density of rare words wins so a doc about crashes beats one that mentions them once
            score = 0.0
            for w in words:
                if counts[w]:
                    df = sum(1 for c in self.counts.values() if c[w])
                    score += (counts[w] / self.lengths[name]) / df
            scores[name] = round(score * 1000, 2)
        best = max(scores, key=scores.get)
        if scores[best] == 0:
            return None
        return {
            "runbook": best,
            "score": round(scores[best], 2),
            "mitigation": self._section(self.docs[best], "## mitigation"),
        }

    def _section(self, text: str, header: str, max_lines: int = 10) -> str:
        lines = text.splitlines()
        out = []
        inside = False
        for line in lines:
            if line.strip().lower().startswith(header):
                inside = True
                continue
            if inside and line.startswith("## "):
                break
            if inside and line.strip():
                out.append(line.rstrip())
            if len(out) >= max_lines:
                break
        return "\n".join(out)
