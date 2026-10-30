#!/usr/bin/env python3
"""Collect official notices for Lanka Weather and write auto-notices.json.

Sources: Department of Meteorology (CAP/RSS alerts), Sri Lanka Navy, Fisheries Department.
Uses only the Python standard library. If a feed cannot be found or read, that source is
skipped and the last good file is kept, so a broken website never wipes or invents notices.

Optional repository variables can pin exact feed addresses:
  METEO_FEED_URL, NAVY_FEED_URL, FISHERIES_FEED_URL
"""
import hashlib, json, os, re, sys, time, urllib.parse, urllib.request
import datetime as dt
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from html import unescape

UA = "LankaWeatherBot/1.0 (+https://github.com/leogayan6841/lanka-weather)"
OUT = os.environ.get("OUT_FILE", "auto-notices.json")
TZ = dt.timezone(dt.timedelta(hours=5, minutes=30))
NOW = dt.datetime.now(TZ)
TODAY = NOW.date()
MAX_AGE_DAYS = 3

SOURCES = [
    {"name": "Department of Meteorology", "home": "https://meteo.gov.lk", "env": "METEO_FEED_URL", "filter": False},
    {"name": "Sri Lanka Navy", "home": "https://www.navy.lk", "env": "NAVY_FEED_URL", "filter": True},
    {"name": "Fisheries Department", "home": "https://www.fisheries.gov.lk", "env": "FISHERIES_FEED_URL", "filter": True},
]
COMMON_PATHS = ["/feed", "/feed/", "/rss", "/rss.xml", "/rss/", "/feed.xml", "/atom.xml", "/cap", "/cap.xml",
                "/rss/cap", "/?feed=rss2", "/index.php?format=feed&type=rss", "/web/index.php?format=feed&type=rss"]
KEYWORDS = re.compile(r"fisher|\bsea\b|\bseas\b|naval|coast|rough|cyclone|depression|warning|advis|alert|tsunami|flood|landslide|lightning|heavy rain|strong wind|weather", re.I)
SEA_TERMS = re.compile(r"sea area|fishermen|fishing|naval|coastal|rough sea|sea condition|deep sea|off the coast", re.I)
DISTRICTS = {
    "colombo": ["colombo"], "gampaha": ["gampaha"], "kalutara": ["kalutara"], "kandy": ["kandy"], "matale": ["matale"],
    "nuwara-eliya": ["nuwara eliya", "nuwaraeliya", "nuwara-eliya"], "galle": ["galle"], "matara": ["matara"],
    "hambantota": ["hambantota", "hambanthota"], "jaffna": ["jaffna"], "kilinochchi": ["kilinochchi"], "mannar": ["mannar"],
    "mullaitivu": ["mullaitivu", "mullativu"], "vavuniya": ["vavuniya"], "trincomalee": ["trincomalee"],
    "batticaloa": ["batticaloa"], "ampara": ["ampara"], "kurunegala": ["kurunegala"], "puttalam": ["puttalam"],
    "anuradhapura": ["anuradhapura"], "polonnaruwa": ["polonnaruwa"], "badulla": ["badulla"],
    "monaragala": ["monaragala", "moneragala"], "ratnapura": ["ratnapura"], "kegalle": ["kegalle", "kegalla"],
}
PROVINCES = ["north western", "north central", "western", "central", "southern", "northern", "eastern", "uva", "sabaragamuwa"]


def log(*a):
    print(*a, file=sys.stderr)


def fetch(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/xml,text/xml,application/rss+xml,application/atom+xml,text/html;q=0.8,*/*;q=0.5"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def ln(tag):
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def text_of(el, name):
    for c in el.iter():
        if ln(c.tag) == name and c.text and c.text.strip():
            return c.text.strip()
    return ""


def clean(s, limit=None):
    s = unescape(re.sub(r"<[^>]+>", " ", s or ""))
    s = re.sub(r"\s+", " ", s).strip()
    if limit and len(s) > limit:
        s = s[: limit - 1].rsplit(" ", 1)[0] + "…"
    return s


def parse_date(s):
    if not s:
        return None
    s = s.strip()
    try:
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        try:
            d = parsedate_to_datetime(s)
        except Exception:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=TZ)
    return d.astimezone(TZ)


def parse_xml(data):
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        return None


# ---------- feed discovery ----------
def candidate_feeds(home):
    cands = []
    try:
        html = fetch(home).decode("utf-8", "ignore")
        for m in re.finditer(r"<link[^>]+>", html, re.I):
            tag = m.group(0)
            if re.search(r"(rss|atom|xml)", tag, re.I):
                h = re.search(r'href=["\']([^"\']+)', tag, re.I)
                if h:
                    cands.append(urllib.parse.urljoin(home, unescape(h.group(1))))
        for m in re.finditer(r'<a[^>]+href=["\']([^"\']+)', html, re.I):
            h = unescape(m.group(1))
            if re.search(r"(rss|atom|/feed|\.xml|cap\b|cap\.|/cap/)", h, re.I) and not h.lower().endswith((".pdf", ".jpg", ".png")):
                cands.append(urllib.parse.urljoin(home, h))
    except Exception as e:
        log(f"  could not read {home}: {e}")
    for p in COMMON_PATHS:
        cands.append(urllib.parse.urljoin(home, p))
    seen, out = set(), []
    for c in cands:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out[:25]


HUB_DIRECTORY = "https://alert-hub-sources.s3.amazonaws.com/json"
KNOWN_METEO_FEED = "https://was.meteo.gov.lk/cap/en/rss.xml"  # from the WMO Alert Hub directory


def hub_candidates():
    """Feed addresses for Sri Lanka from the WMO Alert Hub's public source directory."""
    out = []
    try:
        data = json.loads(fetch(HUB_DIRECTORY, timeout=20).decode("utf-8", "ignore"))
    except Exception as ex:
        log(f"  WMO Alert Hub directory not readable: {type(ex).__name__}")
        return out

    def walk(o):
        if isinstance(o, dict):
            if isinstance(o.get("capAlertFeed"), str):
                blob = json.dumps(o, ensure_ascii=False).lower()
                if o.get("authorityCountry") == "lk" or "sri lanka" in blob:
                    log("  hub entry: " + blob[:400])
                    if o["capAlertFeed"].startswith("http"):
                        out.append(o["capAlertFeed"])
                return
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(data)
    out.sort(key=lambda u: 0 if "/en/" in u else 1)
    if not out:
        log("  no Sri Lanka entry found in the hub directory")
    return out


def load_feed(url):
    root = parse_xml(fetch(url))
    if root is None:
        return None
    if ln(root.tag) in ("rss", "feed", "rdf", "alert"):
        return root
    return None


def items_of(root):
    if ln(root.tag) == "alert":
        return [root]
    return [e for e in root.iter() if ln(e.tag) in ("item", "entry")]


# ---------- CAP + item parsing ----------
def parse_cap(alert):
    infos = [c for c in alert if ln(c.tag) == "info"]
    info = next((i for i in infos if text_of(i, "language").lower().startswith("en")), infos[0] if infos else alert)
    areas = [text_of(a, "areadesc") for a in info.iter() if ln(a.tag) == "area"]
    return {
        "event": text_of(info, "event"), "headline": text_of(info, "headline"), "description": text_of(info, "description"),
        "instruction": text_of(info, "instruction"), "severity": text_of(info, "severity"),
        "effective": text_of(info, "effective") or text_of(alert, "sent"), "expires": text_of(info, "expires"),
        "web": text_of(info, "web"), "areas": [a for a in areas if a],
    }


def entry_link(e):
    for c in e:
        if ln(c.tag) == "link":
            href = c.attrib.get("href") or (c.text or "").strip()
            if href:
                return href, c.attrib.get("type", "")
    return "", ""


def find_cap(e):
    """Return a CAP <alert> for this item: embedded, or via a linked .cap/.xml document."""
    for c in e.iter():
        if ln(c.tag) == "alert":
            return c
    for c in e:
        if ln(c.tag) == "link":
            href, typ = c.attrib.get("href", ""), c.attrib.get("type", "")
            if "cap" in typ or re.search(r"\.(cap|xml)(\?|$)", href, re.I):
                try:
                    r = parse_xml(fetch(href))
                    if r is not None and ln(r.tag) == "alert":
                        return r
                except Exception as ex:
                    log(f"  CAP link failed {href}: {ex}")
    return None


def map_areas(text):
    t = " " + text.lower() + " "
    ids = [i for i, names in DISTRICTS.items() if any(n in t for n in names)]
    for p in PROVINCES:
        if re.search(rf"\b{p} province\b", t):
            ids.append(p)
    if SEA_TERMS.search(text):
        ids.append("coastal")
    return sorted(set(ids)) or ["all"]


def severity_of(cap_sev, text):
    s = (cap_sev or "").lower()
    t = text.lower()
    if s in ("extreme", "severe") or re.search(r"\bred\b|not to venture|refrain from|evacuat", t):
        return "bad"
    if s == "moderate" or re.search(r"amber|yellow|advis|caution|vigilant|warn", t):
        return "warn"
    return "info"


def build_notice(src, e):
    cap = find_cap(e)
    link, _ = entry_link(e)
    if cap is not None:
        c = parse_cap(cap)
        title = c["headline"] or c["event"] or clean(text_of(e, "title"))
        body = " ".join(x for x in [c["description"], c["instruction"]] if x)
        area_txt = ", ".join(c["areas"])
        if area_txt:
            body += f"\nApplies to: {area_txt}"
        start = parse_date(c["effective"]) or parse_date(text_of(e, "pubdate") or text_of(e, "published") or text_of(e, "updated"))
        exp = parse_date(c["expires"])
        link = c["web"] or link
        sev = severity_of(c["severity"], title + " " + body)
        scope_text = " ".join([title, body, area_txt])
    else:
        title = clean(text_of(e, "title"))
        body = clean(text_of(e, "description") or text_of(e, "summary") or text_of(e, "content"), 600)
        start = parse_date(text_of(e, "pubdate") or text_of(e, "published") or text_of(e, "updated") or text_of(e, "date"))
        exp = None
        sev = severity_of("", title + " " + body)
        scope_text = title + " " + body
        if src["filter"] and not KEYWORDS.search(title + " " + body):
            return None
    if not title or start is None:
        return None
    d0 = start.date()
    if (TODAY - d0).days > MAX_AGE_DAYS or d0 > TODAY + dt.timedelta(days=1):
        return None
    expires = exp.date() if exp else d0 + dt.timedelta(days=2)
    if expires < TODAY:
        return None
    key = (link or title) + d0.isoformat()
    return {"id": "auto-" + hashlib.sha1(key.encode()).hexdigest()[:10], "source": src["name"] + " (auto)", "severity": sev,
            "title": clean(title, 140), "text": clean(body, 800) if "\n" not in body else "\n".join(clean(p, 500) for p in body.split("\n")),
            "areas": map_areas(scope_text), "date": d0.isoformat(), "expires": expires.isoformat(),
            **({"link": link} if link.startswith("http") else {})}


def run_source(src):
    status = {"name": src["name"], "feed": None, "ok": False, "items": 0, "notices": 0}
    pinned = os.environ.get(src["env"], "").strip()
    if pinned:
        cands = [pinned]
    else:
        cands = ((hub_candidates() or [KNOWN_METEO_FEED]) if src["name"] == "Department of Meteorology" else []) + candidate_feeds(src["home"])
        cands = list(dict.fromkeys(cands))
    log(f"[{src['name']}] trying {len(cands)} candidate feed address(es)")
    notices = []
    started = time.time()
    for url in cands:
        if time.time() - started > 75:
            log("  time budget for this source used up")
            break
        try:
            root = load_feed(url)
        except Exception as ex:
            log(f"  x {url}  ({type(ex).__name__})")
            continue
        if root is None:
            log(f"  x {url}  (not a feed)")
            continue
        its = items_of(root)
        log(f"  ok {url}  ({len(its)} items)")
        status.update(feed=url, ok=True, items=len(its))
        for e in its[:40]:
            try:
                n = build_notice(src, e)
            except Exception as ex:
                log(f"  item skipped: {ex}")
                n = None
            if n:
                notices.append(n)
        break
    status["notices"] = len(notices)
    return status, notices


def main():
    statuses, allnotices = [], []
    for s in SOURCES:
        try:
            st, n = run_source(s)
        except Exception as ex:
            st, n = {"name": s["name"], "feed": None, "ok": False, "items": 0, "notices": 0, "error": str(ex)[:120]}, []
        statuses.append(st)
        allnotices += n
    if not any(s["ok"] for s in statuses):
        log("No source could be read. Keeping the last good notices.")
        try:
            prev = json.load(open(OUT, encoding="utf-8"))
        except Exception:
            prev = {"notices": []}
        fresh = parse_date(prev.get("updated", ""))
        same_status = [(x["name"], x["ok"]) for x in prev.get("sources", [])] == [(x["name"], x["ok"]) for x in statuses]
        if same_status and fresh and (NOW - fresh) < dt.timedelta(hours=6):
            return 0
        prev.update(updated=NOW.isoformat(timespec="minutes"), sources=statuses)
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(prev, f, ensure_ascii=False, indent=2)
            f.write("\n")
        return 0
    order = {"bad": 0, "warn": 1, "info": 2}
    allnotices.sort(key=lambda n: (order[n["severity"]], n["date"]), reverse=False)
    new = {"updated": NOW.isoformat(timespec="minutes"), "sources": statuses, "notices": allnotices}
    try:
        old = json.load(open(OUT, encoding="utf-8"))
    except Exception:
        old = {}
    same = old.get("notices") == new["notices"] and [(s["name"], s["ok"]) for s in old.get("sources", [])] == [(s["name"], s["ok"]) for s in statuses]
    fresh = parse_date(old.get("updated", ""))
    if same and fresh and (NOW - fresh) < dt.timedelta(hours=6):
        log("No change.")
        return 0
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(new, f, ensure_ascii=False, indent=2)
        f.write("\n")
    log(f"Wrote {OUT}: {len(allnotices)} notice(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
