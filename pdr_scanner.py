
#!/usr/bin/env python3
"""
privacy-sweep — Personal Data Discovery & Opt-out Helper

- Generates discovery/search URLs for people-search/data-broker sites
- Optional best-effort scraping for same-domain links (no JS)
- Prints direct opt-out endpoints for supported sites
- Safer UX flags to minimize broker tracking

License: MIT
"""
import argparse
import csv
import json
import re
import time
import urllib.parse as ul
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional
from pathlib import Path

# Optional imports (only used if --scrape)
try:
    import httpx
    from bs4 import BeautifulSoup
    from fake_useragent import UserAgent
except Exception:
    httpx = None
    BeautifulSoup = None
    UserAgent = None

EMAIL_RE = re.compile(r'[\w\.-]+@[\w\.-]+\.\w+')
PHONE_RE = re.compile(r'(?:(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})')
STATE_ABBR = set("""AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA
MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC""".split())

@dataclass
class QueryParts:
    name: str
    city: Optional[str]
    state: Optional[str]
    emails: List[str]
    phones: List[str]
    raw: str

def smart_parse(query: str) -> QueryParts:
    emails = EMAIL_RE.findall(query or "")
    phones = [re.sub(r'\D', '', p)[-10:] for p in PHONE_RE.findall(query or "")]
    work = query or ""
    for e in emails: work = work.replace(e, ' ')
    for p in PHONE_RE.findall(query or ""): work = work.replace(p, ' ')
    parts = [p.strip() for p in work.split(',') if p.strip()]
    name, city, state = '', None, None
    if parts:
        candidates = [seg for seg in parts if 2 <= len(seg.split()) <= 4]
        name = candidates[0] if candidates else parts[0]
        for seg in parts[1:]:
            tokens = seg.replace('.', ' ').split()
            if tokens:
                maybe_state = tokens[-1].upper()
                if maybe_state in STATE_ABBR:
                    state = maybe_state
                    city = ' '.join(tokens[:-1]) or None
                    break
    name = ' '.join(w.capitalize() if w.isalpha() else w for w in name.split())
    return QueryParts(name=name, city=city, state=state, emails=emails, phones=phones, raw=query or "")

# -------------------- Opt-out links, site groups, config --------------------
OPT_OUT_LINKS = {
    # peoplecore
    "whitepages": "https://www.whitepages.com/suppression_requests",
    "spokeo": "https://www.spokeo.com/opt_out/new",
    "beenverified": "https://www.beenverified.com/app/optout/search",
    "intelius": "https://suppression.peopleconnect.us/login",
    "truthfinder": "https://www.truthfinder.com/opt-out/",
    "fastpeoplesearch": "https://www.fastpeoplesearch.com/removal",
    "truepeoplesearch": "https://www.truepeoplesearch.com/removal",
    "radaris": "https://radaris.com/control/privacy",
    "nuwber": "https://nuwber.com/removal",
    "mylife": "https://www.mylife.com/privacy-policy",
    # brokers_plus
    "freebackgroundcheck": "https://freebackgroundcheck.org/opt-out/",
    "infotracer": "https://infotracer.com/optout/",
    "recordsfinder": "https://recordsfinder.com/opt-out/",
    "affordablebackground": "https://affordablebackgroundchecks.com/remove/",
    "govarrestssearch": "https://govarrestssearch.org/optout/",
    "idstrong": "https://www.idstrong.com/opt-out/",
    "reversephonecheck": "https://www.reversephonecheck.com/optout.php",
    "searchquarry": "https://www.searchquarry.com/opt-out-of-search-quarry/",
    "texaswarrants": "https://texaswarrants.org/remove/",
    "usrecords": "https://usrecords.net/remove/",
    "uswarrants": "https://uswarrants.org/remove/",
    # more_people
    "peoplefinders": "https://www.peoplefinders.com/opt-out",
    "ussearch": "https://suppression.peopleconnect.us/login",
    "peoplelooker": "https://www.peoplelooker.com/opt-out/",
    "addresses": "https://www.addresses.com/optout",
    "neighborwho": "https://www.neighborwho.com/do-not-sell-my-information/",
    "peekyou": "https://www.peekyou.com/about/contact/optout/",
    "thatsthem": "https://thatsthem.com/optout",
    "cocofinder": "https://cocofinder.com/remove-my-info",
    "clustrmaps": "https://clustrmaps.com/bl/opt-out",
}

SITE_GROUPS = {
    "peoplecore": [
        "whitepages","spokeo","beenverified","intelius","truthfinder",
        "fastpeoplesearch","truepeoplesearch","radaris","nuwber"
    ],
    "google": ["google_site_whitepages","google_site_spokeo"],
    "startpage": ["startpage_site_whitepages","startpage_site_spokeo"],
    "brokers_plus": [
        "peoplecore",
        "freebackgroundcheck","infotracer","recordsfinder","affordablebackground",
        "govarrestssearch","idstrong","reversephonecheck","searchquarry",
        "texaswarrants","usrecords","uswarrants"
    ],
    "more_people": [
        "peoplefinders","ussearch","peoplelooker","addresses","neighborwho",
        "peekyou","thatsthem","cocofinder","clustrmaps"
    ],
}

CONFIG_PATH = Path.home() / ".pdr_scanner.json"

def load_config():
    try: return json.loads(CONFIG_PATH.read_text())
    except Exception: return {}

def save_config(cfg: dict):
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
        return True
    except Exception:
        return False

# -------------------- URL patterns --------------------
def site_patterns(q: QueryParts) -> Dict[str, str]:
    first, last = '', ''
    if q.name:
        tokens = q.name.split()
        if len(tokens) >= 2: first, last = tokens[0], tokens[-1]
        else: first = tokens[0]
    city = q.city or ''
    state = q.state or ''
    def enc(s): return ul.quote_plus(s or '')

    patterns = {
        # peoplecore
        "whitepages": f"https://www.whitepages.com/name/{enc(q.name)}/{enc(state)}/{enc(city)}",
        "spokeo": f"https://www.spokeo.com/{enc(first)}-{enc(last)}/{enc(state)}/{enc(city)}",
        "beenverified": f"https://www.beenverified.com/people/{enc(first)}-{enc(last)}/{enc(state.lower())}",
        "intelius": f"https://www.intelius.com/people-search/{enc(first)}-{enc(last)}/{enc(state)}",
        "truthfinder": f"https://www.truthfinder.com/people/{enc(first)}-{enc(last)}/{enc(state)}/",
        "fastpeoplesearch": f"https://www.fastpeoplesearch.com/name/{enc(first)}-{enc(last)}_{enc(city)}-{enc(state)}",
        "truepeoplesearch": f"https://www.truepeoplesearch.com/results?name={enc(q.name)}&citystatezip={enc((city + ' ' + state).strip())}",
        "radaris": f"https://radaris.com/ng/results?ff={enc(first)}&fl={enc(last)}&fc={enc(city)}&fs={enc(state)}",
        "nuwber": f"https://nuwber.com/search?name={enc(q.name)}&location={enc((city + ' ' + state).strip())}",
        # discovery via search engines
        "google_site_whitepages": f"https://www.google.com/search?q=site:whitepages.com+{enc(q.name)}+{enc(city)}+{enc(state)}",
        "google_site_spokeo": f"https://www.google.com/search?q=site:spokeo.com+{enc(q.name)}+{enc(city)}+{enc(state)}",
        "startpage_site_whitepages": f"https://www.startpage.com/do/search?q=site%3Awhitepages.com+{enc(q.name)}+{enc(city)}+{enc(state)}",
        "startpage_site_spokeo": f"https://www.startpage.com/do/search?q=site%3Aspokeo.com+{enc(q.name)}+{enc(city)}+{enc(state)}",
        # additional brokers
        "freebackgroundcheck": f"https://freebackgroundcheck.org/name-search/?q={enc(q.name)}+{enc(city)}+{enc(state)}",
        "infotracer": f"https://infotracer.com/search/?q={enc(q.name)}+{enc(city)}+{enc(state)}",
        "recordsfinder": f"https://recordsfinder.com/people/?name={enc(q.name)}&location={enc((city + ' ' + state).strip())}",
        "affordablebackground": f"https://affordablebackgroundchecks.com/search/?q={enc(q.name)}+{enc(city)}+{enc(state)}",
        "govarrestssearch": f"https://govarrestssearch.org/search/?q={enc(q.name)}+{enc(city)}+{enc(state)}",
        "idstrong": f"https://www.idstrong.com/people-search/?q={enc(q.name)}+{enc(city)}+{enc(state)}",
        "reversephonecheck": f"https://www.reversephonecheck.com/results.php?reporttype=1&fn={enc(first)}&ln={enc(last)}&city={enc(city)}&state={enc(state)}",
        "searchquarry": f"https://www.searchquarry.com/names/?fn={enc(first)}&ln={enc(last)}&state={enc(state)}",
        "texaswarrants": f"https://texaswarrants.org/search/?q={enc(q.name)}+{enc(city)}+{enc(state)}",
        "usrecords": f"https://usrecords.net/search/?q={enc(q.name)}+{enc(city)}+{enc(state)}",
        "uswarrants": f"https://uswarrants.org/search/?q={enc(q.name)}+{enc(city)}+{enc(state)}",
        "peoplefinders": f"https://www.peoplefinders.com/people/{enc(first)}-{enc(last)}?citystatezip={ul.quote_plus((city + ' ' + state).strip())}",
        "ussearch": f"https://www.ussearch.com/people-search/{enc(first)}-{enc(last)}/{enc(state)}",
        "peoplelooker": f"https://www.peoplelooker.com/people/{enc(first)}-{enc(last)}/{enc(state)}/",
        "addresses": f"https://www.addresses.com/people/{enc(first)}+{enc(last)}?state={enc(state)}&city={enc(city)}",
        "neighborwho": f"https://www.neighborwho.com/people-search/{enc(first)}-{enc(last)}/{enc(state)}/?city={enc(city)}",
        "peekyou": f"https://www.peekyou.com/{enc(first)}_{enc(last)}",
        "thatsthem": f"https://thatsthem.com/name/{enc(first)}-{enc(last)}?state={enc(state)}&city={enc(city)}",
        "cocofinder": f"https://cocofinder.com/name?q={enc(q.name)}+{enc(city)}+{enc(state)}",
        "clustrmaps": f"https://clustrmaps.com/person/{enc(first)}-{enc(last)}/{enc(state)}",
    }
    if q.phones:
        for i, ph in enumerate(q.phones, 1):
            patterns[f"google_phone_{i}"] = f"https://www.google.com/search?q={enc(ph)}"
    if q.emails:
        for i, em in enumerate(q.emails, 1):
            patterns[f"google_email_{i}"] = f"https://www.google.com/search?q=%22{enc(em)}%22"
    return patterns

# -------------------- Scoring / scraping --------------------
@dataclass
class ResultItem:
    site: str
    title: str
    url: str
    score: float
    matched_fields: List[str]

def score_link_text(text: str, url: str, q: QueryParts):
    hay = f"{text} {url}".lower()
    score = 0.0
    matched = []
    for tok in q.name.lower().split():
        if tok and tok in hay: score += 0.15; matched.append(tok)
    if q.city and q.city.lower() in hay: score += 0.15; matched.append(q.city)
    if q.state and q.state.lower() in hay: score += 0.10; matched.append(q.state)
    for em in q.emails:
        user = em.split('@')[0].lower()
        if user in hay: score += 0.20; matched.append(em)
    for ph in q.phones:
        last4 = ph[-4:]
        if last4 and last4 in hay: score += 0.20; matched.append(f"*{last4}")
    return min(score, 1.0), matched

def best_effort_scrape(site: str, url: str, q: QueryParts, timeout: float = 15.0) -> List[ResultItem]:
    if httpx is None or BeautifulSoup is None:
        return []
    headers = {}
    if UserAgent is not None:
        try: headers["User-Agent"] = UserAgent().random
        except Exception: pass
    headers.setdefault("User-Agent", "Mozilla/5.0 (compatible; privacy-sweep/1.0)")
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout, headers=headers) as client:
            r = client.get(url)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            from urllib.parse import urlparse
            domain = urlparse(url).netloc.split(':')[0]
            seen, out = set(), []
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if href.startswith("#"): continue
                parsed = urlparse(href)
                host = (parsed.netloc or domain).split(':')[0]
                if domain.split('.')[-2:] != host.split('.')[-2:]: continue
                full = href if parsed.netloc else (f"https://{domain}{href}")
                if full in seen: continue
                seen.add(full)
                text = (a.get_text() or "").strip()
                score, matched = score_link_text(text, full, q)
                if score >= 0.4:
                    out.append(ResultItem(site=site, title=text[:120], url=full, score=score, matched_fields=matched))
            out.sort(key=lambda x: x.score, reverse=True)
            return out[:15]
    except Exception:
        return []

# -------------------- CLI --------------------
import webbrowser

def flatten_sites_arg(arg: str):
    if arg == "all": return ["all"]
    raw = [s.strip().lower() for s in arg.split(",") if s.strip()]
    expanded = []
    for s in raw:
        if s in SITE_GROUPS:
            for item in SITE_GROUPS[s]:
                if item in SITE_GROUPS: expanded.extend(SITE_GROUPS[item])
                else: expanded.append(item)
        else:
            expanded.append(s)
    return expanded

def main():
    ap = argparse.ArgumentParser(description="People/broker discovery + opt-out helpers.")
    ap.add_argument("--query", required=False, help="Free-form string with name and any of: city/state, phone, email.")
    ap.add_argument("--sites", default="peoplecore", help="Comma-separated site keys or groups (peoplecore,google,startpage,brokers_plus,more_people) or 'all'.")
    ap.add_argument("--scrape", action="store_true", help="Attempt to fetch search pages and extract candidate profile URLs (best-effort).")
    ap.add_argument("--open", action="store_true", help="Open generated search URLs in your default browser.")
    ap.add_argument("--limit-open", type=int, default=999, help="Max number of tabs to open when using --open.")
    ap.add_argument("--save-profile", action="store_true", help="Save the provided --query as your default profile in ~/.pdr_scanner.json.")
    ap.add_argument("--use-profile", action="store_true", help="Use the saved default profile when --query is omitted.")
    ap.add_argument("--optout", action="store_true", help="Print opt-out links for supported sites.")
    ap.add_argument("--open-optout", action="store_true", help="Open opt-out links for selected sites in the browser.")
    ap.add_argument("--safe-discovery", action="store_true", help="Only output discovery links (Google/Startpage); never generate or open broker URLs.")
    ap.add_argument("--no-open-non-google", action="store_true", help="When using --open, only open Google/Startpage links; skip broker domains.")
    ap.add_argument("--out", default=None, help="Write CSV to this path.")
    ap.add_argument("--json", dest="json_out", default=None, help="Write JSON to this path.")
    ap.add_argument("--delay", type=float, default=2.0, help="Delay between requests when scraping (seconds).")
    args = ap.parse_args()

    cfg = load_config()
    if getattr(args, "use_profile", False) and not args.query:
        args.query = cfg.get("default_query", "")

    # Allow running optout/open-optout without a query/profile
    if (not args.query) and (not args.use_profile):
        if args.optout or args.open_optout:
            pass
        else:
            ap.error("Provide --query or use --use-profile after saving one with --save-profile.")

    # Safe discovery coercion to discovery-only groups
    if getattr(args, "safe_discovery", False):
        if args.sites == "all":
            args.sites = "google,startpage"
        else:
            wanted_groups = [s.strip() for s in args.sites.split(',') if s.strip()]
            if "google" not in wanted_groups: wanted_groups.insert(0, "google")
            if "startpage" not in wanted_groups: wanted_groups.insert(1, "startpage")
            args.sites = ",".join(wanted_groups)

    q = smart_parse(args.query or "")
    if args.query or args.use_profile:
        print("Parsed query:", asdict(q))

    patterns = site_patterns(q)
    if args.sites == "all":
        wanted_list = list(patterns.keys())
    else:
        wanted_list = flatten_sites_arg(args.sites)
        if "all" in wanted_list:
            wanted_list = list(patterns.keys())

    wanted = set(wanted_list)
    filtered = {k: v for k, v in patterns.items() if k in wanted}

    if args.optout:
        print("\nOpt-out links:")
        opened = 0
        for s in wanted_list:
            if s in OPT_OUT_LINKS:
                url = OPT_OUT_LINKS[s]
                print(f"- {s:18s} {url}")
                if args.open_optout and opened < args.limit_open:
                    try:
                        webbrowser.open_new_tab(url)
                        opened += 1
                    except Exception:
                        pass
        print()
        if (not args.query) and (not args.use_profile):
            return

    print("\nSearch URLs:")
    count_opened = 0
    for site, url in filtered.items():
        if args.safe_discovery and not (site.startswith("google_") or site.startswith("startpage_")):
            continue
        print(f"- {site:22s} {url}")
        if args.open and count_opened < args.limit_open:
            if args.no_open_non_google and not (site.startswith("google_") or site.startswith("startpage_")):
                continue
            try:
                webbrowser.open_new_tab(url)
                count_opened += 1
            except Exception:
                pass
    print()

    rows: List[ResultItem] = []
    if args.scrape and filtered:
        if httpx is None or BeautifulSoup is None:
            print("Scrape requested, but httpx/bs4 not installed. See requirements.txt.")
        else:
            for site, url in filtered.items():
                print(f"[scrape] {site} ...")
                items = best_effort_scrape(site, url, q)
                for it in items:
                    rows.append(it)
                time.sleep(args.delay)

    uniq = {it.url: it for it in rows}
    rows = sorted(uniq.values(), key=lambda x: (x.score, x.site), reverse=True)

    if rows:
        print("\nCandidates:")
        for it in rows:
            print(f"  [{it.score:0.2f}] {it.site:18s} {it.title!r} -> {it.url}")
    else:
        if args.scrape:
            print("No scraped candidates (site may require JS/captcha; link-generation mode still useful).")

    if args.out:
        with open(args.out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["site", "title", "url", "score", "matched_fields"])
            for it in rows:
                w.writerow([it.site, it.title, it.url, f"{it.score:.2f}", ";".join(it.matched_fields)])
        print(f"Wrote CSV: {args.out}")

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump([asdict(it) for it in rows], f, indent=2, ensure_ascii=False)
        print(f"Wrote JSON: {args.json_out}")

if __name__ == "__main__":
    main()
