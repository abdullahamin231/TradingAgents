#!/usr/bin/env python3
"""Bump the Web UI ES module cache key.

The Web UI uses query-string versions on native ES module imports. Browsers cache
each imported module URL separately, so every import edge needs the same fresh key.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FILES = [
    ROOT / "webui" / "templates" / "index.html",
    ROOT / "webui" / "static" / "app.js",
    *sorted((ROOT / "webui" / "static" / "app").glob("*.js")),
]
CACHE_KEY_RE = re.compile(r"v=[A-Za-z0-9._-]+")


def next_cache_key() -> str:
    digest = hashlib.sha256()
    for path in FILES:
        if not path.exists():
            continue
        digest.update(str(path.relative_to(ROOT)).encode("utf-8"))
        digest.update(b"\0")
        text = path.read_text(encoding="utf-8")
        digest.update(CACHE_KEY_RE.sub("v=webui-cache-key", text).encode("utf-8"))
        digest.update(b"\0")
    return f"webui-{digest.hexdigest()[:12]}"


def bump_file(path: Path, cache_key: str) -> bool:
    text = path.read_text(encoding="utf-8")
    updated = CACHE_KEY_RE.sub(f"v={cache_key}", text)
    if updated == text:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", action="store_true", help="stage changed cache-key files")
    parser.add_argument("--fail-on-change", action="store_true", help="exit with status 2 when files are updated")
    args = parser.parse_args()

    cache_key = next_cache_key()
    changed = [path for path in FILES if path.exists() and bump_file(path, cache_key)]

    if args.stage and changed:
        subprocess.run(["git", "add", *[str(path.relative_to(ROOT)) for path in changed]], cwd=ROOT, check=True)

    print(cache_key)
    return 2 if args.fail_on_change and changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
