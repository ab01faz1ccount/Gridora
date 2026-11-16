import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4] / "corpus"
MANIFEST = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8")) if (ROOT / "manifest.json").exists() else {"files": [], "private": []}


def find_private(entry: dict) -> Path | None:
    """A private file by name, else by sha256 (a file may have been renamed, e.g. with a date)."""
    p = ROOT / entry["path"]
    if p.exists():
        return p
    d = ROOT / "private"
    for q in d.glob("*") if d.exists() else []:
        if q.is_file() and q.stat().st_size == entry["bytes"] and hashlib.sha256(q.read_bytes()).hexdigest() == entry["sha256"]:
            return q
    return None


