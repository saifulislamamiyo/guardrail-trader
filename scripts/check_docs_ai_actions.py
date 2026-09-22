"""CI check: every built docs page has the "Ask AI" row, with prompts pointing at its own URL.

  mkdocs build --strict && python scripts/check_docs_ai_actions.py [site_dir]
"""
import html
import re
import sys
import urllib.parse
from pathlib import Path

SITE_URL = "https://saifulislamamiyo.github.io/guardrail-trader/"
RAW = "https://raw.githubusercontent.com/saifulislamamiyo/guardrail-trader/main/docs/"


def main() -> int:
    site = Path(sys.argv[1] if len(sys.argv) > 1 else "site")
    pages = [p for p in site.rglob("index.html") if not {"search", "assets"} & set(p.relative_to(site).parts)]
    bad = []
    for p in sorted(pages):
        rel = p.parent.relative_to(site).as_posix()
        url = SITE_URL + ("" if rel == "." else rel + "/")
        s = p.read_text()
        links = {k: html.unescape(v) for k, v in re.findall(r'data-ai="(\w+)" href="([^"]+)"', s)}
        prompts = [urllib.parse.parse_qs(urllib.parse.urlparse(links.get(k, "")).query).get("q", [""])[0]
                   for k in ("claude", "chatgpt")]
        ok = ('data-ai="copy"' in s and links.get("claude", "").startswith("https://claude.ai/new?q=")
              and links.get("chatgpt", "").startswith("https://chatgpt.com/?q=")
              and links.get("markdown", "").startswith(RAW)
              and all(url in q and links.get("markdown", "") in q for q in prompts)
              and s.count('rel="noopener noreferrer"') >= 3)
        print(f"{'ok ' if ok else 'BAD'} {url}")
        bad += [] if ok else [url]
    print(f"{len(pages)} pages checked, {len(bad)} bad")
    return 1 if bad or not pages else 0


if __name__ == "__main__":
    sys.exit(main())
