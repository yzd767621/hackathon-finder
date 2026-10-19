"""
Hackathon Notifier (free, no API keys, Python standard library + curl)

Finds hackathons that are:
  * free to join
  * open to university / degree students
  * online  -- or, if there is an in-person part (e.g. final presentation), located in Kuala Lumpur / Klang Valley
and shows requirements, team size, difficulty (estimated) and a prize breakdown
(cash in RM vs AI subscriptions vs credits). Malaysian hackathons are listed first.

Sources: Devpost, Devfolio, MLH, Luma (KL), UniNet (uninet.my), GDG Malaysia chapters, Hackathon Radar,
and a DuckDuckGo/Bing search for Malaysian
university / local hackathon sites.
Run:  python hackathon_notifier.py            (normal run, notify on new ones)
      python hackathon_notifier.py --open     (open the report now, refresh it in the background)
"""
import base64
import concurrent.futures as cf
import html
import json
import re
import subprocess
import sys
import time
import urllib.parse
import webbrowser
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE_FILE = HERE / "seen.json"
REPORT_FILE = HERE / "report.html"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"}

KL_STRICT = r"kuala lumpur|\bKL\b|selangor|petaling jaya|cyberjaya|putrajaya|subang|shah alam|bangsar|bukit jalil|klang|puchong|seri kembangan|serdang|sunway|mid valley|damansara|cheras|setapak|bangi|kajang|sepang|\bAPU\b|taylor'?s|universiti malaya|\bUKM\b|\bUPM\b"
KL_WORDS = KL_STRICT + r"|malaysia"
OTHER_MY = r"penang|pulau pinang|johor|sabah|sarawak|kuching|kota kinabalu|perak|ipoh|kedah|melaka|malacca|pahang|kuantan|terengganu|kelantan|negeri sembilan|seremban|perlis|nibong tebal"
MY_WORDS = KL_WORDS + "|" + OTHER_MY + r"|universiti|\bUTM\b|\bUSM\b|\bUiTM\b|\bUUM\b|\bUTP\b|\bMMU\b|\bUNIMAS\b|\bUMS\b|\bXMUM\b|monash malaysia|nottingham malaysia|\bMDEC\b|\.my\b"
OFFLINE_FINAL = r"(in[- ]person|offline|on[- ]?site|physical|onsite)\s+(final|finale|pitch|demo day|presentation|round|showcase)|(grand )?finals?\s+(will be|is|are)\s+(held|hosted|conducted)\s+(in[- ]person|offline|at|in)|finalists?\s+will\s+(be invited|travel|present in person)|travel to"
FEE = r"(registration|entry|entrance|participation|application|ticket)\s+(fee|cost|price)|yuran (pendaftaran|penyertaan)|(fee|pay|charge|cost)[^.\n]{0,30}?(RM|INR|USD|₹|\$)\s?\d+"
NOT_STUDENT = r"high school students only|only (open to )?high school|ages? 13\s*(-|to|–)\s*1[78]|under the age of 18 only|secondary school students only|professionals only|not open to students|employees only|women only|female only|only (open to )?(women|female)"
HACK_NAME = r"hack|\bCTF\b|capture the flag|buildathon|datathon|ideathon|codefest|code fest|game jam|codeathon|innovation challenge"
NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}

# prize classification
AI_TOOLS = r"claude|chatgpt|chat gpt|openai|gemini|perplexity|grok|copilot|anthropic"
AI_SUB = re.compile(rf"\b({AI_TOOLS})\b[^.\n]{{0,40}}\b(pro|plus|max|team|subscriptions?|premium|advanced|ultra|months?|year|membership)\b|"
                    rf"\b(pro|plus|max|subscriptions?|premium|ultra|membership)\b[^.\n]{{0,30}}\b({AI_TOOLS})\b", re.I)
CREDITS = re.compile(r"\bcredits?\b|\bvouchers?\b|\bbaucar\b|\bkredit\b|tín dụng|tokens? worth|api usage|compute (hours|time)|\bcoupons?\b", re.I)
CASH_WORDS = re.compile(r"\bcash\b|tunai|\bwang\b|\bmoney\b|prize pool|tiền mặt|hiện kim", re.I)
NOT_CASH = re.compile(r"worth|value|valued|bernilai|merch|swag|gadget|hardware|device|laptop|phone|tablet|headphone|keyboard|nft|hoodie", re.I)
AMT = r"(\d[\d,.]*\d|\d)"
MONEY = re.compile(rf"(RM|MYR|US\$|USD|S\$|SGD|INR|₹|EUR|€|GBP|£|\$)\s?{AMT}\s?([kK])?\b|"
                   rf"\b{AMT}\s?([kK])?\s?(RM|MYR|USDC|USDT|USD|SGD|INR|EUR|VND|VNĐ)(?!\w)")
CUR_CODE = {"RM": "MYR", "MYR": "MYR", "$": "USD", "US$": "USD", "USD": "USD", "USDC": "USD", "USDT": "USD",
            "S$": "SGD", "SGD": "SGD", "₹": "INR", "INR": "INR", "€": "EUR", "EUR": "EUR", "£": "GBP", "GBP": "GBP",
            "VND": "VND", "VNĐ": "VND"}
RATES = {"USD": 1.0, "MYR": 4.2, "SGD": 1.3, "INR": 88.0, "EUR": 0.9, "GBP": 0.78, "VND": 26000.0}  # fallback; refreshed each run

MONTHS = {"jan": 1, "january": 1, "januari": 1, "feb": 2, "february": 2, "februari": 2, "mar": 3, "march": 3, "mac": 3,
          "apr": 4, "april": 4, "may": 5, "mei": 5, "jun": 6, "june": 6, "jul": 7, "july": 7, "julai": 7,
          "aug": 8, "august": 8, "ogos": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10, "oktober": 10,
          "nov": 11, "november": 11, "dec": 12, "december": 12, "disember": 12}
MON = "(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?"


# ---------------------------------------------------------------- helpers
def fetch(url, data=None, timeout=25):
    # Uses curl.exe (built into Windows 10/11): some sites block Python's urllib.
    cmd = ["curl", "-sSfL", "--compressed", "-m", str(timeout), "-A", UA["User-Agent"],
           "--retry", "2", "--retry-delay", "2", "--retry-all-errors"]  # a slow/busy site shouldn't drop a hackathon
    if data is not None:
        cmd += ["-H", "Content-Type: application/json", "--data-binary", "@-"]
    r = subprocess.run(cmd + [url], input=json.dumps(data).encode() if data is not None else None,
                       capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        raise OSError(f"curl failed ({r.returncode}) for {url}: {r.stderr.decode(errors='replace').strip()}")
    return r.stdout.decode("utf-8", errors="replace")


def safe_fetch(url, timeout=25):
    try:
        return fetch(url, timeout=timeout)
    except Exception:
        return ""


def to_text(page):
    page = re.sub(r"(?is)<(script|style|noscript|svg)\b.*?</\1>", " ", page)
    page = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h\d|tr|section)>", "\n", page)
    page = re.sub(r"<[^>]+>", " ", page)
    page = html.unescape(page)
    page = re.sub(r"[ \t\r\f\v\xa0]+", " ", page)
    return re.sub(r"\n\s*\n+", "\n", page).strip()


def num(s):
    s = s.lower()
    return int(s) if s.isdigit() else NUM_WORDS.get(s)


def team_size(text):
    """Return (min, max) team size parsed from free text; None where unknown."""
    t = text.lower()
    lo = hi = None
    n = r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten)"
    m = re.search(r"team[s]?(?: size)?[^.\n]{0,40}?\b" + n + r"\s*(?:\(\d+\)\s*)?(?:-|to|–|—)\s*" + n + r"\b", t)
    if m:
        lo, hi = num(m.group(1)), num(m.group(2))
    m = re.search(r"(?:minimum of|at least|min\.?|minimum)\s*" + n + r"\s*(?:\(\d+\)\s*)?(?:members?|people|persons|participants|individuals|team ?mates|students)", t)
    if m:
        lo = num(m.group(1))
    m = re.search(r"(?:up to|maximum of|max\.?|maximum|no more than|not exceed)\s*" + n + r"\s*(?:\(\d+\)\s*)?(?:members?|people|persons|participants|individuals|team ?mates|students)", t)
    if m:
        hi = num(m.group(1))
    if lo is None and re.search(r"individual(ly)? or (as )?(a )?team|solo (participants|hackers|entries)|teams? of one|individuals?, teams?|as an individual", t):
        lo = 1
    if lo and hi and lo > hi:
        lo, hi = hi, lo
    return lo, hi


def has_fee(text):
    for m in re.finditer(FEE, text, re.I):
        before = text[max(0, m.start() - 40):m.start()].lower()
        after = text[m.end():m.end() + 25].lower()
        if re.search(r"\bno\b|free|without|waive|zero|not require|percuma|tiada", before + " " + after):
            continue
        return True
    return False


def snippet(text, pattern, width=350):
    m = re.search(pattern, text, re.I)
    if not m:
        return ""
    s = text[m.start():m.start() + width]
    return re.sub(r"\s+", " ", s).strip() + "…"


def judge_location(is_online, location, text):
    """Return (ok, note). Applies: online OK; any offline part must be in KL area."""
    in_kl = bool(re.search(KL_WORDS, location or "", re.I))
    if not is_online:
        if not in_kl:
            return False, ""
        if not re.search(KL_STRICT, location, re.I):
            return True, f"In person: {location} (in Malaysia, check it's in/near KL)"
        return True, f"In person: {location}"
    m = re.search(OFFLINE_FINAL, text, re.I)
    if not m:
        return True, "Fully online"
    ctx = text[max(0, m.start() - 300):m.end() + 300]
    if re.search(KL_STRICT, ctx, re.I) or (re.search("malaysia", ctx, re.I) and not re.search(OTHER_MY, ctx, re.I)):
        return True, "Online, offline final in KL/Malaysia: " + snippet(text, OFFLINE_FINAL, 200)
    return False, ""


PAGE_META = r"last (modified|updated)|updated (on|at)|posted (on|by)|published|copyright|©|all rights reserved|accessed|retrieved|printed on|page (created|modified)"


def event_dates(text):
    """Dates in a page, minus page-housekeeping ones ("Last Modified: 19 October 2026", footers, ©)."""
    return [d for line in text.split("\n") if not re.search(PAGE_META, line, re.I) for d in find_dates(line)]


def find_dates(text):
    out = []
    # ranges like "12-14 Nov 2026" / "Oct 05 - 27, 2026" yield both the start and the end day
    pats = [(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?(?:\s*(?:-|–|to|&|and)\s*(\d{{1,2}})(?:st|nd|rd|th)?)?\s+{MON},?\s+(20\d\d)\b", "dmy"),
            (rf"\b{MON}\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:\s*(?:-|–)\s*(\d{{1,2}})\b)?,?\s+(20\d\d)\b", "mdy"),
            (r"\b(20\d\d)-(\d\d)-(\d\d)\b", "iso")]
    for pat, kind in pats:
        for m in re.finditer(pat, text, re.I):
            try:
                if kind == "dmy":
                    y, mo, days = int(m.group(4)), MONTHS[m.group(3).lower()], [m.group(1), m.group(2)]
                elif kind == "mdy":
                    y, mo, days = int(m.group(4)), MONTHS[m.group(1).lower()], [m.group(2), m.group(3)]
                else:
                    y, mo, days = int(m.group(1)), int(m.group(2)), [m.group(3)]
                out += [date(y, mo, int(d)) for d in days if d]
            except (ValueError, KeyError):
                pass
    return out


# ---------------------------------------------------------------- prizes
def load_rates(state):
    try:
        d = json.loads(fetch("https://open.er-api.com/v6/latest/USD", timeout=15))
        state["rates"] = {k: d["rates"][k] for k in RATES}
    except Exception:
        pass
    RATES.update(state.get("rates", {}))


def money_rm(text):
    """All money amounts in text, converted to RM."""
    out = []
    for m in MONEY.finditer(text):
        cur, amt, k = (m.group(1), m.group(2), m.group(3)) if m.group(1) else (m.group(6), m.group(4), m.group(5))
        # "10.000.000" (dot thousands) vs "1,500.50"
        amt = amt.replace(".", "") if re.fullmatch(r"\d{1,3}(\.\d{3})+", amt) else amt.replace(",", "")
        try:
            v = float(amt) * (1000 if k else 1)
        except ValueError:
            continue
        code = CUR_CODE.get(cur.upper(), CUR_CODE.get(cur, "USD"))
        if v > 0:
            out.append(v / RATES.get(code, 1) * RATES["MYR"])
    return out


def classify(text):
    if AI_SUB.search(text):
        return "ai"
    if CREDITS.search(text):
        return "credits"
    if CASH_WORDS.search(text) or (money_rm(text) and not NOT_CASH.search(text)):
        return "cash"
    return "other"


def summarise_prizes(items):
    """items: [(title, text)] -> dict with tagged lines and totals."""
    lines, cash = [], []
    for title, text in items:
        text = re.sub(r"\s+", " ", text).strip(" •-·")
        if not text:
            continue
        cat = classify(text)
        rm = max(money_rm(text), default=0) if cat == "cash" else 0
        if rm:
            cash.append(rm)
        lines.append({"cat": cat, "title": title, "text": text[:220], "rm": rm})
    cats = {l["cat"] for l in lines}
    return {"lines": lines[:25], "cash_top": max(cash, default=0), "cash_total": sum(cash),
            "ai": "ai" in cats, "credits": "credits" in cats, "cash": bool(cash) or "cash" in cats}


def prize_lines_from_text(text):
    """Pull prize-looking lines out of free text (Luma / university sites)."""
    out = []
    for line in text.split("\n"):
        line = line.strip()
        if 4 < len(line) < 300 and re.search(r"champion|winner|runner|place|prize|hadiah|johan|naib|grand|1st|2nd|3rd|first|second|third|best|consolation|saguhati|top \d", line, re.I) \
                and (MONEY.search(line) or CREDITS.search(line) or AI_SUB.search(line) or re.search(r"cash|tunai", line, re.I)):
            out.append(("", line))
    return out[:15]


def rm(v):
    return f"RM {v:,.0f}"


# ---------------------------------------------------------------- difficulty
BEGINNER = r"beginner[- ]friendly|beginners? (are )?welcome|no (prior |previous )?(coding |programming )?experience|first[- ]time hackers?|all skill levels|newbies?|learn(ing)? to code"
HARD_THEMES = r"blockchain|web3|quantum|robotic|ar/vr|iot|cybersecurity|devops|serverless|enterprise|fintech|hardware|embedded"
SPONSOR_TECH = r"(must|required to|need to|should) (use|integrate|build (on|with)|leverage) (the |at least one )?[A-Z][\w.-]+ (sdk|api|platform|model|cloud)"


def difficulty(h, text):
    """Estimate (level, reason). No site publishes difficulty, so this is a heuristic."""
    reasons, score = [], 0
    usd = h["prizes"]["cash_total"] / RATES["MYR"]
    if usd >= 100000:
        score += 2
        reasons.append(f"very large cash prizes ({rm(h['prizes']['cash_total'])}), tough competition")
    elif usd >= 20000:
        score += 1
        reasons.append(f"large cash prizes ({rm(h['prizes']['cash_total'])})")
    if re.search(HARD_THEMES, h.get("themes", ""), re.I):
        score += 1
        reasons.append("specialised tech (" + ", ".join(sorted({m.lower() for m in re.findall(HARD_THEMES, h["themes"], re.I)})) + ")")
    if re.search(SPONSOR_TECH, text):
        score += 1
        reasons.append("must use a sponsor's SDK/API")
    if "Beginner Friendly" in h.get("themes", "") or re.search(BEGINNER, text, re.I):
        score -= 1
        reasons.append("organisers say beginners welcome")
    elif score == 0:
        reasons.append("small or no prize pool, open-ended")
    level = "Beginner" if score <= 0 else "Intermediate" if score == 1 else "Advanced"
    return level, "; ".join(reasons)


# ---------------------------------------------------------------- sources
def devpost_item(h, kind):
    loc = (h.get("displayed_location") or {}).get("location") or ""
    if kind is None:
        kind = "online" if re.search(r"online", loc, re.I) else "in-person"
    if h.get("invite_only") or (kind == "in-person" and not re.search(KL_WORDS, loc, re.I)):
        return None
    amount = int(re.sub(r"\D", "", re.sub(r"<[^>]+>", "", h.get("prize_amount") or "")) or 0)
    return {
        "id": f"devpost:{h['id']}", "source": "Devpost", "title": h["title"],
        "url": h["url"].rstrip("/"), "online": kind == "online", "location": loc,
        "dates": h.get("submission_period_dates", ""), "left": h.get("time_left_to_submission", ""),
        "organizer": h.get("organization_name") or "", "listed_usd": amount,
        "themes": ", ".join(t["name"] for t in h.get("themes", [])),
    }


def devpost():
    base = "https://devpost.com/api/hackathons?status[]=open&status[]=upcoming&open_to[]=public&{}&page={}"
    out, seen = [], set()
    for kind, q in [("online", "challenge_type[]=online"), ("in-person", "challenge_type[]=in-person"),
                    (None, "search=Malaysia"), (None, "search=Kuala%20Lumpur"), (None, "search=Selangor")]:
        try:
            first = json.loads(fetch(base.format(q, 1)))
        except Exception as e:
            print("Devpost error:", e)
            FAILED_SOURCES.add("Devpost")
            continue
        n_pages = -(-first["meta"]["total_count"] // first["meta"]["per_page"])
        with cf.ThreadPoolExecutor(max_workers=8) as pool:
            rest = list(pool.map(lambda p: json.loads(safe_fetch(base.format(q, p)) or "{}"), range(2, n_pages + 1)))
        if any(not d for d in rest):
            FAILED_SOURCES.add("Devpost")
        for d in [first] + rest:
            for h in d.get("hackathons", []):
                if h["id"] in seen:
                    continue
                seen.add(h["id"])
                item = devpost_item(h, kind)
                if item:
                    out.append(item)
    return out


def devpost_prizes(page):
    items = []
    for chunk in page.split('id="prize_')[1:]:
        chunk = re.split(r'id="prize_|id="judges"|</section>', chunk)[0]
        title = to_text(re.search(r'class="prize-title">(.*?)</h6>', chunk, re.S).group(1)) if 'class="prize-title"' in chunk else ""
        val = re.search(r'class="prize-value">(.*?)</div>', chunk, re.S)
        if val:
            items.append((title, to_text(val.group(1))))
        desc = re.search(r"<p>(.*?)</p>", chunk, re.S)
        if desc:
            for line in to_text(desc.group(1)).split("\n"):
                items.append((title, line))
        if not val and not desc and title:
            items.append((title, title))
    return items


def devpost_detail(h):
    page = safe_fetch(h["url"] + "/")
    home = to_text(page)
    if not home:
        return "retry"
    rules = to_text(safe_fetch(h["url"] + "/rules"))
    who = ""
    m = re.search(r"Who can participate\s*(.*?)\s*View full rules", home, re.S)
    if m:
        who = re.sub(r"\s+", " ", m.group(1)).strip()
    full = home + "\n" + rules
    # Devpost sidebar lists excluded/included countries in a popup:
    # "Specific countries/territories excluded × Specific countries/territories excluded A B C No countries/territories match your search."
    m = re.search(r"Specific countries/territories (excluded|included) × Specific countries/territories \1 (.*?) No countries/territories match your search\.?", who)
    if m:
        kind, countries = m.groups()
        if (kind == "excluded") == ("malaysia" in countries.lower()):
            return None  # Malaysia excluded, or not on the allowed list
        who = who.replace(m.group(0), f"Countries {kind}: {countries}")
    elif re.search(r"Specific countries/territories included", who):
        return None  # allowed list not readable; play safe
    # Devpost's own eligibility tags
    if re.search(r"Ages? (13|14|15|16) to (1[3-8]) only|High school students only|Professionals/Post grads only|Post grads only", who, re.I):
        return None
    reqs = []
    if who:
        reqs.append("Who can join: " + who)
    sub = snippet(rules, r"(submission requirements|what to submit|requirements\s*:|project requirements)", 450)
    if sub:
        reqs.append(sub)
    return full, reqs, devpost_prizes(page)


def devfolio():
    out, start = [], 0
    while True:
        try:
            d = json.loads(fetch("https://api.devfolio.co/api/search/hackathons",
                                 {"type": "application_open", "from": start, "size": 50}))
        except Exception as e:
            print("Devfolio error:", e)
            break
        hits = d["hits"]["hits"]
        for x in hits:
            s = x["_source"]
            loc = ", ".join(p for p in [s.get("location") or s.get("city"), s.get("country")] if p)
            if not s.get("is_online") and not re.search(KL_WORDS, loc, re.I):
                continue
            desc = s.get("desc") or ""
            elig = snippet(desc, r"(eligib|who can (apply|participate|join))", 350)
            out.append({
                "id": f"devfolio:{s['uuid']}", "source": "Devfolio", "title": s["name"],
                "url": f"https://{s['slug']}.devfolio.co/", "online": bool(s.get("is_online")),
                "location": "Online" if s.get("is_online") else loc,
                "dates": f"{(s.get('starts_at') or '')[:10]} → {(s.get('ends_at') or '')[:10]}", "left": "",
                "organizer": s.get("tagline") or "", "themes": ", ".join(s.get("hashtags") or []),
                "_text": desc, "_team": (s.get("team_min"), s.get("team_size")), "_reqs": [elig] if elig else [],
                "_prizes": [(p.get("name") or "", f"{p.get('name') or ''}: {p.get('desc') or ''}" if p.get("desc") else p.get("name") or "")
                            for p in s.get("prizes") or []],
            })
        start += len(hits)
        if not hits or start >= d["hits"]["total"]["value"]:
            break
    return out


def mlh():
    out = []
    year = datetime.now().year + (1 if datetime.now().month >= 7 else 0)
    try:
        page = fetch(f"https://www.mlh.com/seasons/{year}/events")
        m = re.search(r'<script data-page="app" type="application/json">(.*?)</script>', page, re.S)
        events = json.loads(m.group(1))["props"].get("upcomingEvents", [])
    except Exception as e:
        print("MLH error:", e)
        return out
    for e in events:
        fmt, loc = e.get("formatType"), e.get("location") or ""
        if fmt != "digital" and not re.search(KL_WORDS, loc, re.I):
            continue
        out.append({
            "id": f"mlh:{e['id']}", "source": "MLH", "title": e["name"],
            "url": e.get("websiteUrl") or "https://www.mlh.com" + e.get("url", ""),
            "online": fmt == "digital", "location": "Online" if fmt == "digital" else f"{loc} ({fmt})",
            "dates": f"{e.get('startsAt', '')[:10]} → {e.get('endsAt', '')[:10]}", "left": "",
            "organizer": "MLH member event", "themes": "",
            "_reqs": ["MLH events are free and student-focused; you must agree to the MLH Code of Conduct."],
        })
    return out


def prosemirror_text(node, out):
    if isinstance(node, dict):
        if node.get("type") == "text":
            out.append(node.get("text", ""))
        for v in node.values():
            prosemirror_text(v, out)
        if node.get("type") in ("paragraph", "heading", "list_item", "hard_break"):
            out.append("\n")
    elif isinstance(node, list):
        for x in node:
            prosemirror_text(x, out)
    return out


def luma():
    """Free hackathon-type events on Luma's Kuala Lumpur page."""
    found = {}
    for q in ("hackathon", "buildathon", "hack", "datathon", "ideathon", "ctf", "game%20jam", "competition", "challenge"):
        try:
            d = json.loads(fetch("https://api.lu.ma/discover/get-paginated-events?discover_place_api_id="
                                 f"discplace-O15L1VZiYe0GYGm&pagination_limit=50&query={q}"))
        except Exception as e:
            print("Luma error:", e)
            continue
        for x in d.get("entries", []):
            ev = x["event"]
            if re.search(HACK_NAME, ev["name"], re.I) and not re.search(r"workshop|talk|meetup|networking", ev["name"], re.I):
                found[x["api_id"]] = x
    out = []
    for api_id, x in found.items():
        ev, tix = x["event"], x.get("ticket_info") or {}
        if not tix.get("is_free"):
            continue
        geo = ev.get("geo_address_info") or {}
        online = ev.get("location_type") == "online"
        loc = "Online" if online else ", ".join(p for p in [geo.get("sublocality"), geo.get("city_state") or geo.get("city")] if p)
        out.append({
            "id": f"luma:{api_id}", "source": "Luma", "title": ev["name"], "url": f"https://luma.com/{ev['url']}",
            "online": online, "location": loc, "dates": (ev.get("start_at") or "")[:10], "left": "",
            "organizer": (x.get("calendar") or {}).get("name") or "", "themes": "", "_api_id": api_id,
        })
    return out


def luma_detail(h):
    try:
        d = json.loads(fetch(f"https://api.lu.ma/event/get?event_api_id={h['_api_id']}"))
    except Exception:
        return None
    return "".join(prosemirror_text(d.get("description_mirror"), []))


def gdg():
    """Hackathons run by Google Developer Groups chapters in Malaysia (GDG on Campus UM, APU, Sunway, MMU, ...)."""
    out, page = [], 1
    while page:
        try:
            d = json.loads(fetch(f"https://gdg.community.dev/api/event/?status=Live&page={page}", timeout=60))
        except Exception as e:
            print("GDG error:", e)
            break
        for e in d.get("results", []):
            ch = e.get("chapter") or {}
            if ch.get("country") != "MY" or not re.search(HACK_NAME, e["title"], re.I):
                continue
            out.append({
                "id": f"gdg:{e['id']}", "source": "GDG", "title": e["title"], "url": e["url"], "online": None,
                "location": ch.get("city") or "", "left": "", "organizer": ch.get("title") or "", "themes": "",
                "dates": f"{(e.get('start_date') or '')[:10]} → {(e.get('end_date') or '')[:10]}",
            })
        page = (d.get("pagination") or {}).get("next_page")
    return out


def gdg_detail(h):
    page = safe_fetch(h["url"])
    if not page:
        return "retry"
    text = to_text(page)
    m = re.search(r"\b(online|virtual|hybrid)\b", text[:4000], re.I)
    h["online"] = bool(m)
    if h["online"]:
        h["location"] = "Online"
    return text


def radar():
    """Hackathon Radar (hackathonradar.com) aggregates many platforms; keep its upcoming Malaysian entries."""
    try:
        page = fetch("https://www.hackathonradar.com/", timeout=60).replace('\\"', '"')
    except Exception as e:
        print("Hackathon Radar error:", e)
        return []
    out = []
    for raw in re.findall(r'\{"id":"[^"]+","title":"[^{}]*?"url":"/database/hackathon/[^"]+"\}', page):
        try:
            r = json.loads(raw)
        except ValueError:
            continue
        if r.get("country") != "Malaysia" or (r.get("endAt") or "")[:10] < date.today().isoformat():
            continue
        out.append({
            "id": f"radar:{r['id']}", "source": "Hackathon Radar", "title": r["title"],
            "url": "https://www.hackathonradar.com" + r["url"], "online": False,
            "location": ", ".join(x for x in [r.get("venueName"), r.get("city"), "Malaysia"] if x),
            "dates": f"{(r.get('startAt') or '')[:10]} → {(r.get('endAt') or '')[:10]}", "left": "",
            "organizer": "", "themes": "",
        })
    return out


def radar_detail(h):
    page = safe_fetch(h["url"])
    if not page:
        return "retry"
    for block in re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', page, re.S):
        try:
            d = json.loads(block)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("@type") == "Event":
            if "Online" in (d.get("eventAttendanceMode") or ""):
                h["online"], h["location"] = True, "Online"
            return (d.get("description") or "") + "\n" + to_text(page)
    return to_text(page)


UNINET_TYPES = r"hackathon|datathon|ideathon|innovation challenge|\bCTF\b|programming competition"


def uninet():
    """UniNet (uninet.my): Malaysian university student events. Uses its public sitemap + each event's schema.org data."""
    try:
        locs = re.findall(r"<loc>(https://uninet\.my/events/[^<]+)</loc>", fetch("https://uninet.my/sitemap.xml"))
    except Exception as e:
        print("UniNet error:", e)
        return []

    def event(url):
        for block in re.findall(r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", safe_fetch(url), re.S):
            try:
                d = json.loads(block)
            except ValueError:
                continue
            if isinstance(d, dict) and d.get("@type") == "Event":
                return d

    with cf.ThreadPoolExecutor(max_workers=8) as pool:
        events = [e for e in pool.map(event, locs) if e]
    out = []
    for e in events:
        kinds = e.get("keywords") or ""
        if not re.search(UNINET_TYPES, kinds, re.I) and not re.search(HACK_NAME, e["name"], re.I):
            continue
        if re.search(r"webinar|workshop|talk", kinds, re.I) and not re.search(r"competition|hackathon|datathon", kinds, re.I):
            continue  # e.g. an info session about a hackathon
        deadline = (e.get("offers") or {}).get("validThrough") or ""
        if deadline and deadline[:10] < date.today().isoformat():
            continue  # registration closed
        out.append({
            "id": "uninet:" + e["url"].rsplit("/", 1)[-1], "source": "UniNet", "title": html.unescape(e["name"]),
            "url": e["url"], "online": None, "location": "", "left": "",
            "dates": f"register by {deadline[:10]}" if deadline else "registration deadline not stated",
            "organizer": (e.get("organizer") or {}).get("name") or "", "themes": kinds,
            "_text": html.unescape(e.get("description") or ""), "_free": e.get("isAccessibleForFree"),
        })
    return out


def uninet_detail(h):
    """UniNet gives no location field: read online / KL from the description."""
    text = h.pop("_text")
    if h.pop("_free") is False:
        return None
    blob = h["title"] + "\n" + text
    if re.search(r"\b(online|virtual|hybrid|remote|dalam talian)\b", blob, re.I):
        h["online"], h["location"] = True, "Online"
    else:
        kl, other = re.search(KL_STRICT, blob, re.I), re.search(OTHER_MY, blob, re.I)
        if other and not kl:
            return None  # in person outside KL
        h["online"], h["location"] = False, (kl.group(0).title() + ", Malaysia") if kl else "Malaysia (venue not stated)"
    # descriptions arrive as one paragraph; split bullets / sentences into lines for prize parsing
    return re.sub(r"\s+(?=[-•▪➤✅🏆🥇🥈🥉💰🎁]\s?)|(?<=[.!?])\s+", "\n", text)


SKIP_DOMAINS = r"coursera|hackathon\.com|uninet\.my|gdg\.community\.dev|hackathonradar\.com|devpost\.com|devfolio\.co|lu\.ma|luma\.com|facebook|instagram|linkedin|youtube|twitter|x\.com|tiktok|reddit|eventbrite|mlh\.(io|com)|wikipedia|threads\.net"
GENERIC_PAGE = r"\bhackathons\b(?! ?(20\d\d|v\d))|opportunit(y|ies) (desk|for)|what is a hackathon|how to|guide|find .{0,20}hackathons|upcoming hackathons|hackathons worldwide|list of|directory|^hackathon$"
PAST_WORDS = r"\b(secure[sd]?|wins?|won|raih|johan|juara|recap|congratulat\w*|tahniah|emerged|bags?|clinch\w*|triumph\w*|highlights)\b"


def ddg(query):
    page = safe_fetch("https://html.duckduckgo.com/html/?q=" + urllib.parse.quote_plus(query))
    out = []
    for m in re.finditer(r'class="result__a" href="([^"]+)"[^>]*>(.*?)</a>(.*?)class="result__snippet"[^>]*>(.*?)</a>', page, re.S):
        href = html.unescape(m.group(1))
        url = urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("uddg", [href])[0]
        if "duckduckgo.com/y.js" in url:
            continue  # ad
        out.append((url, to_text(m.group(2)), to_text(m.group(4))))
    return out or bing(query)  # DuckDuckGo sometimes shows a bot check: fall back to Bing


def bing(query):
    page = safe_fetch("https://www.bing.com/search?q=" + urllib.parse.quote_plus(query))
    out = []
    for m in re.finditer(r'<li class="b_algo".*?<h2[^>]*><a[^>]+href="([^"]+)"[^>]*>(.*?)</a></h2>(.*?)</li>', page, re.S):
        href = html.unescape(m.group(1))
        enc = re.search(r"[?&]u=a1([^&]+)", href)  # bing.com/ck/a?...&u=a1<base64 url>
        try:
            url = base64.urlsafe_b64decode(enc.group(1) + "=" * (-len(enc.group(1)) % 4)).decode() if enc else href
        except ValueError:
            continue
        snip = re.search(r"<p[^>]*>(.*?)</p>", m.group(3), re.S)
        out.append((url, to_text(m.group(2)), to_text(snip.group(1)) if snip else ""))
    return out


def web(state):
    """Discover Malaysian / university hackathon sites via DuckDuckGo; remember them for 60 days."""
    y = date.today().year
    queries = [f"hackathon {y} Malaysia registration", f"hackathon {y} universiti Malaysia",
               f"hackathon Kuala Lumpur {y} prize RM", f"online hackathon Malaysia students {y}",
               f"hackathon {y + 1} Malaysia", f"varsity hackathon {y} Malaysia",
               f"pertandingan hackathon {y}", f"hackathon {y} pendaftaran universiti", f"hackathon Selangor {y}",
               f"datathon OR ideathon Malaysia {y}", f"CTF competition Malaysia {y} university",
               f"hackathon {y} Malaysia cash prize students"]
    def wanted(url, title, snip):
        host = urllib.parse.urlparse(url).netloc
        if re.search(SKIP_DOMAINS, host, re.I) or re.search(PAST_WORDS, title, re.I) or re.search(GENERIC_PAGE, title, re.I):
            return False
        if not re.search(HACK_NAME, title + " " + snip, re.I):
            return False
        if not re.search(MY_WORDS, " ".join([title, snip, host]), re.I):
            return False  # search engines pad results with non-Malaysian pages
        return not any(int(yr) < y for yr in re.findall(r"\b(20\d\d)\b", title))  # last year's edition

    known = {u: v for u, v in state.get("web_urls", {}).items() if wanted(u, v["title"], v.get("snip", ""))}
    for q in queries:
        for url, title, snip in ddg(q):
            url = re.sub(r"[?&](msockid|utm_[a-z]+|fbclid|gclid)=[^&]*", "", url)  # tracking codes
            if wanted(url, title, snip):
                known.setdefault(url, {"title": title, "snip": snip[:300], "first": date.today().isoformat()})
        time.sleep(1.5)  # be polite to the search engine
    cutoff = date.today().toordinal() - 60
    known = {u: v for u, v in known.items() if date.fromisoformat(v["first"]).toordinal() >= cutoff}
    state["web_urls"] = known
    return [{"id": "web:" + re.sub(r"^https?://(www\.)?", "", u).rstrip("/"), "source": "Web", "title": v["title"],
             "url": u, "online": None, "location": "", "dates": "", "left": "", "organizer": urllib.parse.urlparse(u).netloc,
             "themes": ""} for u, v in known.items()]


def web_detail(h):
    page = safe_fetch(h["url"], timeout=20)
    if not page:
        return "retry"
    meta =" ".join(html.unescape(m) for m in re.findall(r'<meta[^>]+(?:name|property)="(?:og:)?description"[^>]+content="([^"]*)"', page))
    title = re.search(r"<title[^>]*>(.*?)</title>", page, re.S | re.I)
    text = to_text(page) + "\n" + meta
    if len(text) < 800:  # JavaScript-only site: the visible text lives in its script bundle
        for src in re.findall(r'<script[^>]+src="([^"]+\.js)"', page)[:3]:
            src = urllib.parse.urljoin(h["url"], src)
            if urllib.parse.urlparse(src).netloc == urllib.parse.urlparse(h["url"]).netloc:
                js = safe_fetch(src, timeout=30)
                text += "\n" + "\n".join(s for s in re.findall(r'"([^"\\]{4,300})"', js) if " " in s and re.search(r"[A-Za-z]{3}", s))
    if not re.search(HACK_NAME, text, re.I):
        return None
    future = sorted(d for d in event_dates(text) if d >= date.today())
    if not future:
        return None  # no upcoming date on the page: probably over
    if title and to_text(title.group(1)):
        h["title"] = to_text(title.group(1))[:120]
    h["dates"] = f"next date on site: {future[0].isoformat()}"
    if re.search(r"\b(online|virtual|hybrid|remote|dalam talian)\b", text, re.I):
        h["online"], h["location"] = True, "Online"
    else:
        m = re.search(KL_STRICT, text, re.I)
        if not m or (re.search(OTHER_MY, text, re.I) and len(re.findall(OTHER_MY, text, re.I)) > len(re.findall(KL_STRICT, text, re.I))):
            return None
        h["online"], h["location"] = False, m.group(0).title() + ", Malaysia"
    return text


# ---------------------------------------------------------------- pipeline
FEE_REJECTED = set()  # title keys of hackathons that charge a fee on any site
REJECTED = set()  # ids a filter turned down this run (vs. pages that just failed to load)
FAILED_SOURCES = set()  # sources that errored or only partly loaded this run


def title_key(title):
    return re.sub(r"[^a-z0-9]", "", title.lower())[:12]


def reject(h):
    REJECTED.add(h["id"])
    return None


FREE_TEXT_SOURCES = ("UniNet", "Luma", "Web", "GDG", "Hackathon Radar")
NEVER_THE_EVENT = r"masterclass|project sharing|sharing session|preparation|prep session|briefing|info(rmation)? session|webinar|sharing session|roadshow|open day|awards? ceremony|prize[- ]giving|closing ceremony|launch(ing)? (event|ceremony)|town ?hall|watch party|career fair|recruitment"
SIDE_EVENT = r"workshop|\btalk\b|meetup|seminar|bootcamp|masterclass|training|course|study jam|info day"
COMPETITION = r"hackathon|buildathon|datathon|ideathon|\bCTF\b|capture the flag|challenge|competition|game jam|codefest"


# Malaysian student-event feeds list many innovation expos / business / testing competitions; only
# keep things that call themselves a hackathon (or a close cousin).
STRICT_HACK = r"hack|buildathon|datathon|ideathon|codeathon|codefest|\bCTF\b|capture the flag|game jam|\bjam\b"
SCHOOL_ONLY = r"\bschool (innovation|students?|competition|category|level)|secondary school|sekolah|primary school|\bSPM\b"


def not_a_hackathon(title, labels=""):
    """Briefings / webinars / workshops *about* a hackathon, non-hackathon competitions, school-pupil events."""
    return bool(re.search(NEVER_THE_EVENT, title, re.I) or re.search(SCHOOL_ONLY, title, re.I) or
                re.search(GENERIC_PAGE, title, re.I) or
                not re.search(STRICT_HACK, title + " " + labels, re.I) or
                (re.search(SIDE_EVENT, title, re.I) and not re.search(COMPETITION, title, re.I)))


def evaluate(h, cache):
    """Fetch details, apply filters. Returns enriched dict or None."""
    if h["source"] in FREE_TEXT_SOURCES and not_a_hackathon(h["title"], h.get("themes", "")):
        return reject(h)
    c = cache.get(h["id"])
    if h["source"] == "Devpost":
        if c and "prizes" in c:
            text, reqs, prize_items = c["text"], c["reqs"], c["prizes"]
        else:
            r = devpost_detail(h)
            if r == "retry":  # page didn't load: try again next run
                return None
            if r is None:
                return reject(h)
            text, reqs, prize_items = r
        if not prize_items and h["listed_usd"]:
            prize_items = [("", f"${h['listed_usd']:,} in prizes (type not stated, check the page)")]
        lo, hi = team_size(text)
        who = reqs[0] if reqs and reqs[0].startswith("Who can join") else ""
        m = re.search(r"Team required: (\d+) to (\d+) members", who)
        if m:  # Devpost's own structured field wins
            lo, hi = int(m.group(1)), int(m.group(2))
        elif "Team required" in who:
            lo = max(lo or 2, 2)
        elif who:  # Devpost shows "Team required" when solo isn't allowed
            lo = 1
    elif h["source"] == "Devfolio":
        text, reqs, prize_items = h.pop("_text"), h.pop("_reqs"), h.pop("_prizes")
        lo, hi = h.pop("_team")
    elif h["source"] == "MLH":  # details live on the event's own site
        text = (c or {}).get("text") or to_text(safe_fetch(h["url"]))
        reqs, prize_items = h.pop("_reqs"), prize_lines_from_text(text)
        lo, hi = team_size(text)
        if lo is None and hi is None:
            hi = 4  # MLH standard rule
    else:  # Luma / UniNet / GDG / Hackathon Radar / Web: free-text pages
        text = {"Luma": luma_detail, "UniNet": uninet_detail, "GDG": gdg_detail,
                "Hackathon Radar": radar_detail}.get(h["source"], web_detail)(h)
        if text == "retry" or (text is None and h["source"] == "Luma"):  # page didn't load
            return None
        if not text or not_a_hackathon(h["title"], h.get("themes", "")):  # web pages swap in their own <title>
            return reject(h)
        h.pop("_api_id", None)
        elig = snippet(text, r"(eligib\w*|who (can|should) (join|apply|participate)|open to|kelayakan|syarat)", 300)
        reqs = [elig] if elig else []
        prize_items = prize_lines_from_text(text)
        lo, hi = team_size(text)
    if hi and hi > 20:  # e.g. "up to 100 participants" isn't a team size
        hi = None
    if has_fee(text):
        FEE_REJECTED.add(title_key(h["title"]))
        return reject(h)
    if re.search(NOT_STUDENT, text, re.I):
        return reject(h)
    ok, note = judge_location(h["online"], h["location"], text)
    if not ok:
        return reject(h)
    h["prizes"] = summarise_prizes(prize_items)
    h["malaysia"] = h["source"] in ("Luma", "Web", "GDG", "Hackathon Radar") or bool(
        re.search(MY_WORDS, " ".join([h["title"], h["location"], h["organizer"]]
                                     + ([text] if h["source"] == "UniNet" else [])), re.I)) or \
        any(re.search(r"\bRM\s?\d|\bMYR\b", l["text"]) for l in h["prizes"]["lines"])
    level, why = difficulty(h, text)
    h.update(text=text[:60000], reqs=reqs, team_min=lo, team_max=hi, mode=note, level=level, level_why=why,
             _prize_items=prize_items)
    return h


def team_label(h):
    lo, hi = h.get("team_min"), h.get("team_max")
    if lo and hi:
        return f"Team: min {lo}, max {hi}"
    if lo:
        return f"Team: min {lo}"
    if hi:
        return f"Team: max {hi} (solo likely OK)"
    return "Team: not stated"


def days_left(h):
    """Rough days until deadline, for sorting."""
    m = re.search(r"(\d+|a|an|about \d+|about a)\s*(hour|day|week|month|year)s? left", h.get("left", ""))
    if m:
        n = re.sub(r"\D", "", m.group(1)) or "1"
        return int(n) * {"hour": 0.04, "day": 1, "week": 7, "month": 30, "year": 365}[m.group(2)]
    end = re.findall(r"\d{4}-\d{2}-\d{2}", h.get("dates", ""))
    if end:
        return (datetime.fromisoformat(end[-1]) - datetime.now()).days + 1
    return 999


def notify(new):
    if not new:
        return
    my = [h for h in new if h.get("malaysia")]
    title = f"{len(new)} new hackathon(s) found" + (f", {len(my)} in Malaysia" if my else "")
    body = "; ".join(h["title"] for h in (my + [h for h in new if not h.get("malaysia")])[:3]) + (" …" if len(new) > 3 else "")
    esc = lambda s: html.escape(s, quote=True)
    xml = (f'<toast activationType="protocol" launch="{esc(REPORT_FILE.as_uri())}"><visual><binding template="ToastGeneric">'
           f"<text>{esc(title)}</text><text>{esc(body)}</text></binding></visual></toast>")
    ps = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null
$x = New-Object Windows.Data.Xml.Dom.XmlDocument
$x.LoadXml(@'
{xml}
'@)
$app = '{{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}}\\WindowsPowerShell\\v1.0\\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($x))
"""
    enc = base64.b64encode(ps.encode("utf-16-le")).decode()
    subprocess.run(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-EncodedCommand", enc],
                   capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Hackathon Finder</title><style>
:root{{--bg:#f6f7f9;--card:#fff;--fg:#1d2330;--mute:#667085;--acc:#2f6fed;--line:#e4e7ec;--chip:#eef1f5;
--beg:#1f8a4c;--begbg:#e3f5ea;--mid:#9a6700;--midbg:#fff4d6;--adv:#c2372e;--advbg:#fde7e5;
--cash:#0f7b3f;--cashbg:#d9f7e6;--ai:#6b3fd4;--aibg:#ece5ff;--cred:#8a5a00;--credbg:#fbefd5;--my:#0b5cad;--mybg:#dcebfc}}
@media (prefers-color-scheme:dark){{:root{{--bg:#12151b;--card:#1b2029;--fg:#e6e9ef;--mute:#98a2b3;--acc:#7aa2ff;--line:#2b313c;--chip:#262c37;
--beg:#5fd08d;--begbg:#173323;--mid:#f0c050;--midbg:#3a2f12;--adv:#ff7b72;--advbg:#3d1a18;
--cash:#5fe39a;--cashbg:#123a25;--ai:#b9a2ff;--aibg:#2a2147;--cred:#f0c050;--credbg:#3a2f12;--my:#8cc4ff;--mybg:#152c47}}}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,Segoe UI,sans-serif}}
main{{max-width:840px;margin:auto;padding:20px 16px 40px}} h1{{margin:0;font-size:24px}}
.sub{{color:var(--mute);font-size:13px;margin:4px 0 14px}}
.bar{{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-bottom:8px}} .bar b{{font-size:13px;color:var(--mute);margin-right:2px;min-width:62px}}
.bar button,.bar select{{font:inherit;font-size:13px;border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:999px;padding:5px 12px;cursor:pointer}}
.bar button.on{{background:var(--acc);border-color:var(--acc);color:#fff}} .bar select{{margin-left:auto}}
.item{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:8px 0}}
.item.my{{border-left:4px solid var(--my)}}
.item a.t{{color:var(--fg);font-weight:600;font-size:16px;text-decoration:none}} .item a.t:hover{{color:var(--acc)}}
.chips{{display:flex;flex-wrap:wrap;gap:6px;margin-top:7px}}
.chip{{font-size:12.5px;padding:2px 9px;border-radius:999px;background:var(--chip)}}
.Beginner{{color:var(--beg);background:var(--begbg);font-weight:600}} .Intermediate{{color:var(--mid);background:var(--midbg);font-weight:600}}
.Advanced{{color:var(--adv);background:var(--advbg);font-weight:600}}
.cash{{color:var(--cash);background:var(--cashbg);font-weight:600}} .ai{{color:var(--ai);background:var(--aibg);font-weight:600}}
.credits{{color:var(--cred);background:var(--credbg);font-weight:600}} .mychip{{color:var(--my);background:var(--mybg);font-weight:600}}
.new{{background:#e5484d;color:#fff;font-size:11px;padding:1px 6px;border-radius:4px;margin-left:6px;vertical-align:2px}}
details{{margin-top:8px;font-size:13.5px}} summary{{cursor:pointer;color:var(--acc)}}
details ul{{margin:6px 0 0;padding-left:18px}} details li{{margin:3px 0}} .mute{{color:var(--mute)}}
.tag{{display:inline-block;min-width:74px;text-align:center;font-size:11px;font-weight:700;padding:1px 6px;border-radius:4px;margin-right:6px;background:var(--chip)}}
h4{{margin:10px 0 2px;font-size:13.5px}}
.banner{{background:var(--acc);color:#fff;padding:8px 12px;border-radius:8px;margin-bottom:12px;font-size:14px}}
.sec{{margin-top:22px}} .sec h2{{font-size:18px;margin:0;display:flex;align-items:center;gap:8px}}
.count{{font-size:12px;font-weight:600;background:var(--chip);color:var(--mute);border-radius:999px;padding:1px 9px}}
.newsec{{background:var(--card);border:1px solid var(--line);border-top:3px solid #e5484d;border-radius:12px;padding:14px 14px 6px}}
.newsec .item{{background:var(--bg)}} .newsec .count{{background:#e5484d;color:#fff}}
.small{{font-size:13px;margin:2px 0 6px}} .found{{font-size:12px;color:#e5484d;font-weight:600;margin-left:6px}}
</style></head><body><main><h1>Hackathon Finder</h1>
<p class="sub">{count} free hackathons ({my_count} in Malaysia) · open to degree students · online, or in person in KL · updated {stamp}<br>
Difficulty is an estimate and USD is converted at 1 USD = RM {rate:.2f}. Check the official rules before you register.</p>
<div class="bar" data-g="where"><b>Show</b><button class="on" data-f="all">All</button><button data-f="my">Malaysia only</button>
<button data-f="cash">Cash prizes</button><button data-f="ai">AI subscription prizes</button><button data-f="nocred">Hide credits-only</button></div>
<div class="bar" data-g="level"><b>Level</b><button class="on" data-f="all">Any</button><button data-f="Beginner">Beginner</button>
<button data-f="Intermediate">Intermediate</button><button data-f="Advanced">Advanced</button>
<select id="sort"><option value="m">Malaysia first</option><option value="d">Deadline</option><option value="p">Biggest cash prize</option></select></div>
<section class="sec newsec"><h2>New this week <span class="count" data-for="new">{new_count}</span></h2>
<p class="mute small">Found in the last 7 days{new_hint}</p><div class="list" id="new">{new_rows}</div></section>
<section class="sec"><h2>All hackathons <span class="count" data-for="all">{all_count}</span></h2><div class="list" id="all">{rows}</div></section></main>
<script>
const lists=[...document.querySelectorAll('.list')],sel={{where:'all',level:'all'}};
function apply(){{lists.forEach(list=>{{let n=0;list.querySelectorAll('.item').forEach(i=>{{const d=i.dataset,w=sel.where;
const okW=w==='all'||(w==='my'&&d.my==='1')||(w==='cash'&&+d.cash>0)||(w==='ai'&&d.ai==='1')||(w==='nocred'&&d.credonly!=='1');
i.hidden=!(okW&&(sel.level==='all'||d.level===sel.level));n+=!i.hidden}});
document.querySelector('.count[data-for="'+list.id+'"]').textContent=n}})}}
document.querySelectorAll('.bar[data-g]').forEach(bar=>bar.querySelectorAll('button').forEach(b=>b.onclick=()=>{{
sel[bar.dataset.g]=b.dataset.f;bar.querySelectorAll('button').forEach(x=>x.classList.toggle('on',x===b));apply()}}));
document.getElementById('sort').onchange=e=>{{const k=e.target.value;lists.forEach(list=>
[...list.children].sort((a,b)=>k==='p'?b.dataset.cash-a.dataset.cash:k==='m'?(b.dataset.my-a.dataset.my)||(a.dataset.days-b.dataset.days):a.dataset.days-b.dataset.days).forEach(x=>list.appendChild(x)))}};
</script></body></html>"""

TAG_LABEL = {"cash": "CASH", "ai": "AI SUB", "credits": "CREDITS", "other": "OTHER"}


def prize_chips(p):
    chips = []
    if p["cash_top"]:
        chips.append(f'<span class="chip cash">Cash: top prize {rm(p["cash_top"])}</span>')
    elif p["cash"]:
        chips.append('<span class="chip cash">Cash (amount not stated)</span>')
    if p["ai"]:
        chips.append('<span class="chip ai">AI subscription</span>')
    if p["credits"]:
        chips.append('<span class="chip credits">' + ("+ credits" if p["cash"] or p["ai"] else "Credits only, no cash") + "</span>")
    if not chips:
        chips.append('<span class="chip">' + ("Non-cash prizes only" if p["lines"] else "Prizes not listed") + "</span>")
    return chips


def found_label(first_seen):
    days = (datetime.now(timezone.utc) - datetime.fromisoformat(first_seen)).days
    return "found today" if days == 0 else "found yesterday" if days == 1 else f"found {days} days ago"


def write_report(items, seen, baseline):
    """Hackathons first seen in the last 7 days (after the initial setup batch) go in "New this week" at the top."""
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    is_new = lambda h: seen.get(h["id"], "") > max(baseline, week_ago)
    new_rows, rows = [], []
    for h in sorted(items, key=lambda h: (not h["malaysia"], days_left(h))):
        (new_rows if is_new(h) else rows).append(item_html(h, found_label(seen[h["id"]]) if is_new(h) else ""))
    REPORT_FILE.write_text(PAGE.format(
        count=len(items), my_count=sum(h["malaysia"] for h in items), rate=RATES["MYR"],
        new_count=len(new_rows), all_count=len(rows),
        new_hint="" if new_rows else ". Nothing new yet: the app checks every day and will notify you.",
        new_rows="".join(new_rows), rows="".join(rows) or "<p>No matching hackathons right now.</p>",
        stamp=datetime.now().strftime("%d %b %Y, %H:%M")), encoding="utf-8")


def item_html(h, found):
    e = html.escape
    p, d = h["prizes"], days_left(h)
    reqs = "".join(f"<li>{e(r)}</li>" for r in h["reqs"]) or "<li>See the event page</li>"
    plines = "".join(
        f'<li><span class="tag {l["cat"]}">{TAG_LABEL[l["cat"]]}</span>'
        f'{e((l["title"] + ": ") if l["title"] and l["title"] not in l["text"] else "")}{e(l["text"])}'
        f'{f" <span class=mute>(≈ {rm(l["rm"])})</span>" if l["rm"] and not re.search(r"RM|MYR", l["text"]) else ""}</li>'
        for l in p["lines"]) or "<li>No prize details found, check the event page.</li>"
    if p["cash_total"]:
        plines = f'<li><b>Total cash: about {rm(p["cash_total"])}</b> (≈ ${p["cash_total"] / RATES["MYR"]:,.0f})</li>' + plines
    more = " · ".join(x for x in [h["organizer"], h["dates"], f"via {h['source']}"] if x)
    fmt = "Online" if h["mode"] == "Fully online" else h["mode"]
    plural = "" if int(d) == 1 else "s"
    left = h["left"] or (f"{int(d)} day{plural} left" if d < 999 and h["source"] != "Web" else f"next date in {int(d)} day{plural}" if d < 999 else "")
    chips = (['<span class="chip mychip">Malaysia</span>'] if h["malaysia"] else []) + \
            [f'<span class="chip {h["level"]}" title="{e(h["level_why"])}">{h["level"]}</span>'] + prize_chips(p) + \
            [f'<span class="chip">{e(team_label(h))}</span>', f'<span class="chip">{e(fmt[:60])}</span>'] + \
            ([f'<span class="chip">{e(left)}</span>'] if left else []) + \
            (['<span class="chip" title="The site did not respond this time, so this is from the previous check">from last check</span>']
             if h.get("missed") else [])
    new = f'<span class="new">NEW</span><span class="found">{found}</span>' if found else ""
    long_fmt = f'<li class="mute">Format: {e(h["mode"])}</li>' if len(fmt) > 60 else ""
    web_note = '<li class="mute">Found by web search: details were read from the event site automatically, so double-check them.</li>' if h["source"] == "Web" else ""
    credonly = "1" if p["credits"] and not p["cash"] and not p["ai"] else "0"
    return f"""<div class="item{' my' if h['malaysia'] else ''}" data-level="{h['level']}" data-cash="{p['cash_top']:.0f}" data-ai="{int(p['ai'])}" data-credonly="{credonly}" data-my="{int(h['malaysia'])}" data-days="{d}">
<a class="t" href="{e(h['url'])}" target="_blank">{e(h['title'])}</a>{new}
<div class="chips">{''.join(chips)}</div>
<details><summary>Prizes &amp; requirements</summary>
<h4>Prizes</h4><ul>{plines}</ul>
<h4>Requirements</h4><ul>{reqs}
<li class="mute">Why {h['level'].lower()}: {e(h['level_why'])}</li>{long_fmt}{web_note}
<li class="mute">{e(more)}</li></ul></details></div>"""


def show_updating():
    """Open the last report right away with an 'updating' banner; it reloads itself until the new one is written."""
    old = REPORT_FILE.read_text(encoding="utf-8") if REPORT_FILE.exists() else \
        PAGE.format(count=0, my_count=0, rate=RATES["MYR"], new_count=0, all_count=0, new_hint="", new_rows="",
                    rows="", stamp="never")
    REPORT_FILE.write_text(old.replace("<title>", '<meta http-equiv="refresh" content="4"><title>', 1)
                              .replace("<main>", '<main><div class="banner">Checking for new hackathons… this page reloads by itself.</div>', 1),
                           encoding="utf-8")
    webbrowser.open(REPORT_FILE.as_uri())
    return old


def main():
    old_page = show_updating() if "--open" in sys.argv else None
    try:
        run()
    except Exception:
        if old_page is not None:  # don't leave the page stuck reloading
            REPORT_FILE.write_text(old_page, encoding="utf-8")
        raise


def run():
    state = json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}
    state.setdefault("seen", {})
    state.setdefault("cache", {})
    if "baseline" not in state:  # hackathons found on the setup day aren't "new"
        first = min(state["seen"].values(), default=None)
        if first:  # midnight after the setup day, in local (Malaysia) time
            day = datetime.fromisoformat(first).astimezone().date() + timedelta(days=1)
            state["baseline"] = datetime.combine(day, datetime.min.time()).astimezone().astimezone(timezone.utc).isoformat()
        else:
            state["baseline"] = datetime.now(timezone.utc).isoformat()
    load_rates(state)

    candidates = []
    sources = [devpost, devfolio, mlh, luma, uninet, gdg, radar, lambda: web(state)]
    names = ["devpost", "devfolio", "mlh", "luma", "uninet", "gdg", "hackathon radar", "web"]
    with cf.ThreadPoolExecutor(max_workers=len(sources)) as pool:
        for name, fut in zip(names, [pool.submit(s) for s in sources]):
            try:
                got = fut.result()
                print(f"{name}: {len(got)} candidates")
                candidates += got
            except Exception as ex:
                print(f"{name} failed: {ex}")
                FAILED_SOURCES.add(name)

    with cf.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda h: evaluate(h, state["cache"]), candidates))
    items, keys = [], set()
    for h in results:  # drop duplicates (same hackathon found on two sites)
        if not h:
            continue
        key = title_key(h["title"])
        if key in keys or key in FEE_REJECTED:
            continue
        keys.add(key)
        items.append(h)

    # A hackathon that was listed last time but didn't load now (site slow/down) is kept from the last
    # check, unless a filter turned it down, its deadline passed, or it has been missing 3 runs in a row.
    current, tried = {h["id"] for h in items}, {h["id"] for h in candidates}
    for pid, old in state.get("items", {}).items():
        key = title_key(old["title"])
        if pid in current or pid in REJECTED or key in keys or key in FEE_REJECTED or old.get("missed", 0) >= 3:
            continue
        if pid not in tried and old["source"] not in FAILED_SOURCES and old["source"].lower() not in FAILED_SOURCES:
            continue  # its site loaded fine and no longer lists it
        ends = find_dates(old.get("dates", ""))
        if ends and max(ends) < date.today():
            continue
        old["missed"] = old.get("missed", 0) + 1
        keys.add(key)
        items.append(old)
    carried = sum(1 for h in items if h.get("missed"))

    new = [h for h in items if h["id"] not in state["seen"]]
    now = datetime.now(timezone.utc).isoformat()
    for h in new:
        state["seen"][h["id"]] = now
    state["cache"] = {h["id"]: {"text": h["text"], "reqs": h["reqs"], "prizes": h["_prize_items"]}
                      for h in items if h["source"] in ("Devpost", "MLH") and "text" in h}
    state["items"] = {h["id"]: {k: v for k, v in h.items() if k not in ("text", "_prize_items")} for h in items}
    STATE_FILE.write_text(json.dumps(state), encoding="utf-8")

    write_report(items, state["seen"], state["baseline"])
    print(f"{len(items)} matching hackathons ({sum(h['malaysia'] for h in items)} in Malaysia, {len(new)} new, "
          f"{carried} kept from last check). Report: {REPORT_FILE}")
    notify(new)


if __name__ == "__main__":
    main()
