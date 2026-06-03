"""
Detect the technology stack of a company website via HTTP headers, HTML, and pattern matching.

Usage:
    python tools/fetch_tech_signals.py --domain stripe.com --company-id stripe
    python tools/fetch_tech_signals.py --company-id stripe
    python tools/fetch_tech_signals.py --companies-file data/companies.json

Exit codes: 0 success, 1 partial, 2 fatal
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def load_tech_fingerprints(path: str = "data/tech_keywords.json") -> list:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("technologies", [])
    except Exception as e:
        print(f"[tech] cannot load tech_keywords.json: {e}", file=sys.stderr)
        return []


def detect_from_headers(headers: dict, fingerprints: list) -> list:
    detected = []
    headers_lower = {k.lower(): v.lower() for k, v in headers.items()}
    headers_str = json.dumps(headers_lower).lower()

    for tech in fingerprints:
        patterns = tech.get("patterns", {})
        for header_pattern in patterns.get("headers", []):
            if header_pattern.lower() in headers_str:
                detected.append({
                    "name": tech["name"],
                    "category": tech.get("category", ""),
                    "confidence": 0.92,
                    "evidence": f"HTTP header: {header_pattern}",
                })
                break

    return detected


def detect_from_html(soup: BeautifulSoup, response_text: str, fingerprints: list) -> list:
    detected = []
    detected_names = set()
    text_lower = response_text.lower()

    for tech in fingerprints:
        if tech["name"] in detected_names:
            continue
        patterns = tech.get("patterns", {})

        for script_pattern in patterns.get("scripts", []):
            if script_pattern.lower() in text_lower:
                detected.append({
                    "name": tech["name"],
                    "category": tech.get("category", ""),
                    "confidence": 0.92,
                    "evidence": f"script src contains '{script_pattern}'",
                })
                detected_names.add(tech["name"])
                break

        if tech["name"] in detected_names:
            continue

        for meta_pattern in patterns.get("meta", []):
            meta_tag = soup.find("meta", attrs={"name": meta_pattern.get("name", "")})
            if meta_tag:
                content = meta_tag.get("content", "").lower()
                if meta_pattern.get("content", "").lower() in content:
                    detected.append({
                        "name": tech["name"],
                        "category": tech.get("category", ""),
                        "confidence": 0.95,
                        "evidence": f"meta tag: {meta_pattern}",
                    })
                    detected_names.add(tech["name"])
                    break

        if tech["name"] in detected_names:
            continue

        for cookie_pattern in patterns.get("cookies", []):
            if cookie_pattern.lower() in text_lower:
                detected.append({
                    "name": tech["name"],
                    "category": tech.get("category", ""),
                    "confidence": 0.75,
                    "evidence": f"cookie pattern: {cookie_pattern}",
                })
                detected_names.add(tech["name"])
                break

    return detected


def generate_outreach_signals(detected: list, icp_path: str = "data/icp_criteria.json") -> list:
    signals = []
    try:
        with open(icp_path, encoding="utf-8") as f:
            icp = json.load(f)
        target_tech = [t.lower() for t in icp.get("technographics", {}).get(
            "positive_tech_signals", {}).get("technologies", [])]
        for d in detected:
            if d["name"].lower() in target_tech:
                signals.append(f"Uses {d['name']} ({d['category']}) — ICP tech signal match")
    except Exception:
        pass

    cats = {d["category"] for d in detected}
    if "Analytics / CDP" in cats or "Analytics" in cats:
        signals.append("Data-mature org (analytics tooling detected)")
    if "Monitoring / Observability" in cats:
        signals.append("Engineering culture signal (monitoring tools present)")
    if "Customer Support / Chat" in cats:
        signals.append("Customer-focused (live chat / support tool active)")

    return signals[:5]


def scan_domain(domain: str, company_id: str = None) -> dict:
    for scheme in ("https", "http"):
        url = f"{scheme}://{domain}"
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml",
            }
            resp = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
            if resp.status_code < 400:
                break
        except requests.exceptions.SSLError:
            if scheme == "https":
                continue
            return {"domain": domain, "company_id": company_id, "error": "ssl_error", "fetched_at": _now()}
        except Exception as e:
            return {"domain": domain, "company_id": company_id, "error": str(e), "fetched_at": _now()}
    else:
        return {"domain": domain, "company_id": company_id, "error": "unreachable", "fetched_at": _now()}

    fingerprints = load_tech_fingerprints()
    soup = BeautifulSoup(resp.text, "lxml")

    detected_from_headers = detect_from_headers(dict(resp.headers), fingerprints)
    detected_from_html = detect_from_html(soup, resp.text, fingerprints)

    all_detected = {}
    for d in detected_from_headers + detected_from_html:
        name = d["name"]
        if name not in all_detected or d["confidence"] > all_detected[name]["confidence"]:
            all_detected[name] = d

    final_detected = sorted(all_detected.values(), key=lambda x: x["confidence"], reverse=True)

    cdn = None
    for tech in final_detected:
        if tech["category"] in ("CDN / Security", "CDN"):
            cdn = tech["name"]
            break

    server = resp.headers.get("Server", "")
    x_powered_by = resp.headers.get("X-Powered-By", "")

    outreach_signals = generate_outreach_signals(final_detected)

    is_spa = bool(
        soup.find("div", id="root") or soup.find("div", id="app") or soup.find("div", id="__next")
    ) and len(resp.text) < 20000

    return {
        "company_id": company_id,
        "domain": domain,
        "scanned_at": _now(),
        "final_url": resp.url,
        "status_code": resp.status_code,
        "tech_stack": final_detected,
        "tech_count": len(final_detected),
        "headers_analyzed": {
            "server": server or None,
            "x_powered_by": x_powered_by or None,
            "content_type": resp.headers.get("Content-Type", ""),
        },
        "cdn": cdn,
        "is_likely_spa": is_spa,
        "signals_for_outreach": outreach_signals,
    }


def main():
    parser = argparse.ArgumentParser(description="Detect tech stack from website headers and HTML")
    parser.add_argument("--domain", help="Domain to scan (e.g. stripe.com)")
    parser.add_argument("--company-id", help="Company ID")
    parser.add_argument("--companies-file", default="data/companies.json")
    parser.add_argument("--output-dir", help="Write output files to this directory")
    args = parser.parse_args()

    if args.domain:
        result = scan_domain(args.domain, args.company_id)
        if args.output_dir and args.company_id:
            Path(args.output_dir).mkdir(parents=True, exist_ok=True)
            out_path = Path(args.output_dir) / f"tech_{args.company_id}_{_today()}.json"
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2)
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(2 if "error" in result else 0)

    if args.company_id:
        with open(args.companies_file, encoding="utf-8") as f:
            data = json.load(f)
        company = next((c for c in data["companies"] if c["id"] == args.company_id), None)
        if not company:
            print(json.dumps({"error": "company_id not found"}))
            sys.exit(2)
        domain = company.get("domain") or company.get("website", "").replace("https://", "").replace("http://", "").rstrip("/")
        result = scan_domain(domain, args.company_id)
        if args.output_dir:
            Path(args.output_dir).mkdir(parents=True, exist_ok=True)
            out_path = Path(args.output_dir) / f"tech_{args.company_id}_{_today()}.json"
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2)
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(2 if "error" in result else 0)

    with open(args.companies_file, encoding="utf-8") as f:
        data = json.load(f)

    all_results = []
    errors = []
    for company in data["companies"]:
        domain = company.get("domain") or company.get("website", "").replace("https://", "").replace("http://", "").rstrip("/")
        if not domain:
            continue
        try:
            result = scan_domain(domain, company["id"])
            all_results.append(result)
            if args.output_dir:
                Path(args.output_dir).mkdir(parents=True, exist_ok=True)
                out_path = Path(args.output_dir) / f"tech_{company['id']}_{_today()}.json"
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(result, f, indent=2)
        except Exception as e:
            errors.append({"company_id": company["id"], "error": str(e)})

    print(json.dumps({
        "fetched_at": _now(),
        "companies_scanned": len(all_results),
        "errors": errors,
        "results": all_results,
    }, ensure_ascii=False))
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
