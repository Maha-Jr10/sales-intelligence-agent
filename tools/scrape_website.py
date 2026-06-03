"""
Fetch any URL and return structured text content, stripping HTML noise.

Usage:
    python tools/scrape_website.py --url https://example.com
    python tools/scrape_website.py --url https://example.com --selector ".job-listing"
    python tools/scrape_website.py --url https://example.com --output-format text

Exit codes: 0 success, 1 partial, 2 fatal
"""

import argparse
import hashlib
import json
import sys
import time
import urllib.parse
import urllib.robotparser
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]

STRIP_TAGS = ["script", "style", "nav", "footer", "head", "iframe", "noscript", "svg"]


def get_user_agent(url: str) -> str:
    idx = int(hashlib.md5(url.encode()).hexdigest(), 16) % len(USER_AGENTS)
    return USER_AGENTS[idx]


def is_allowed_by_robots(url: str, timeout: int = 5) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(robots_url)
        rp.read()
        return rp.can_fetch("*", url)
    except Exception:
        return True


def fetch_url(url: str, timeout: int = 10, selector: str = None) -> dict:
    headers = {
        "User-Agent": get_user_agent(url),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

    try:
        response = requests.get(url, headers=headers, timeout=timeout,
                                allow_redirects=True)
    except requests.exceptions.Timeout:
        return {"url": url, "error": "timeout", "fetched_at": _now()}
    except requests.exceptions.TooManyRedirects:
        return {"url": url, "error": "too_many_redirects", "fetched_at": _now()}
    except requests.exceptions.ConnectionError as e:
        # One retry
        try:
            time.sleep(2)
            response = requests.get(url, headers=headers, timeout=timeout,
                                    allow_redirects=True)
        except Exception:
            return {"url": url, "error": "connection_error", "detail": str(e), "fetched_at": _now()}

    content_type = response.headers.get("Content-Type", "")
    if response.status_code in (403, 429):
        return {
            "url": url,
            "error": "blocked",
            "status_code": response.status_code,
            "fetched_at": _now(),
        }
    if response.status_code >= 400:
        return {
            "url": url,
            "error": "http_error",
            "status_code": response.status_code,
            "fetched_at": _now(),
        }
    if "text/html" not in content_type and "application/xhtml" not in content_type:
        return {
            "url": url,
            "error": "non_html_content",
            "content_type": content_type,
            "status_code": response.status_code,
            "fetched_at": _now(),
        }

    soup = BeautifulSoup(response.text, "lxml")

    title = soup.title.string.strip() if soup.title and soup.title.string else ""

    for tag in soup(STRIP_TAGS):
        tag.decompose()

    if selector:
        elements = soup.select(selector)
        content_soup = BeautifulSoup(
            " ".join(str(e) for e in elements), "lxml"
        ) if elements else soup
    else:
        content_soup = soup

    text_content = " ".join(content_soup.get_text(separator=" ").split())

    links = []
    base_parsed = urllib.parse.urlparse(url)
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith("http"):
            links.append(href)
        elif href.startswith("/"):
            links.append(f"{base_parsed.scheme}://{base_parsed.netloc}{href}")

    links = list(dict.fromkeys(links))[:100]

    return {
        "url": response.url,
        "fetched_at": _now(),
        "status_code": response.status_code,
        "title": title,
        "text_content": text_content[:50000],
        "links": links,
        "metadata": {
            "content_length": len(response.text),
            "encoding": response.encoding,
            "selector_used": selector,
        },
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main():
    parser = argparse.ArgumentParser(description="Fetch and parse a URL to structured text")
    parser.add_argument("--url", required=True, help="URL to fetch")
    parser.add_argument("--selector", help="CSS selector to narrow content extraction")
    parser.add_argument("--output-format", choices=["json", "text"], default="json")
    parser.add_argument("--skip-robots", action="store_true", help="Skip robots.txt check")
    parser.add_argument("--timeout", type=int, default=10)
    args = parser.parse_args()

    if not args.skip_robots and not is_allowed_by_robots(args.url, args.timeout):
        result = {
            "url": args.url,
            "error": "disallowed_by_robots_txt",
            "fetched_at": _now(),
        }
        print(json.dumps(result))
        sys.exit(1)

    result = fetch_url(args.url, timeout=args.timeout, selector=args.selector)

    if args.output_format == "text" and "text_content" in result:
        print(result["text_content"])
    else:
        print(json.dumps(result, ensure_ascii=False))

    sys.exit(2 if "error" in result else 0)


if __name__ == "__main__":
    main()
