"""llms.txt must point at real docs and cover every public docs page."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_PREFIX = "https://raw.githubusercontent.com/umutkeltek/healthsave-observatory/main/"
LINK = re.compile(r"\]\((https?://[^)\s]+)\)")


def _linked_paths() -> set[str]:
    text = (ROOT / "llms.txt").read_text()
    urls = LINK.findall(text)
    assert urls, "llms.txt has no links"
    outside = [url for url in urls if not url.startswith(RAW_PREFIX)]
    assert not outside, f"llms.txt links outside this repo's raw docs: {outside}"
    return {url.removeprefix(RAW_PREFIX) for url in urls}


def test_llms_txt_links_resolve_to_repo_files():
    missing = sorted(path for path in _linked_paths() if not (ROOT / path).is_file())
    assert not missing, f"llms.txt links to files that do not exist: {missing}"


def test_llms_txt_lists_every_public_docs_page():
    docs = {path.relative_to(ROOT).as_posix() for path in (ROOT / "docs").rglob("*.md")}
    unlisted = sorted(docs - _linked_paths())
    assert not unlisted, f"add these docs pages to llms.txt: {unlisted}"
