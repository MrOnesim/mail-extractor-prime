import os
import re
import socket
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Optional

import dns.resolver

DNS_TIMEOUT = float(os.environ.get("MAILLENS_DNS_TIMEOUT", "2.0"))
DNS_CACHE_TTL = int(os.environ.get("MAILLENS_DNS_TTL", "300"))
DNS_WORKERS = min(int(os.environ.get("MAILLENS_DNS_WORKERS", "16")), 32)
RECENT_WINDOW_DAYS = int(os.environ.get("MAILLENS_RECENT_WINDOW", "730"))

EMAIL_REGEX = re.compile(
    r"(?<![@\w.])[A-Za-z0-9][A-Za-z0-9._%+-]*@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![@\w])"
)

TYPO_MAP = {
    "gmail.com": ["gamil.com", "gnail.com", "gmaill.com", "gmal.com", "gmial.com",
                   "gmao.com", "gmai.com", "gamil.co", "gmial.co"],
    "hotmail.com": ["hotmial.com", "hotmil.com", "hotmal.com", "hotmai.com",
                     "hotmail.co", "hotmial.fr"],
    "outlook.com": ["outlok.com", "outloo.com", "outlok.co"],
    "yahoo.com": ["yaho.com", "yaoo.com", "yhoo.com", "yaho.fr"],
    "protonmail.com": ["protonmail.co", "protonmial.com", "prontonmail.com"],
    "proton.me": ["protn.me", "proton.me", "prton.me"],
    "live.com": ["live.co", "liev.com"],
    "laposte.net": ["laposte.nets"],
    "orange.fr": ["orane.fr", "orange.fr", "oragn.fr", "orang.fr"],
    "sfr.fr": ["sfr.co", "sffr.fr"],
    "free.fr": ["free.co", "fre.fr"],
    "wanadoo.fr": ["wanado.fr", "wannadoo.fr"],
}

REVERSE_TYPO = {}
for _correct, _wrongs in TYPO_MAP.items():
    for _wrong in _wrongs:
        REVERSE_TYPO[_wrong] = _correct

PROVIDER_PATTERNS = {
    "gmail": re.compile(r"(^|\.)gmail\.com$", re.IGNORECASE),
    "outlook": re.compile(r"(^|\.)(outlook|hotmail|live|msn)\.(com|fr)$", re.IGNORECASE),
    "yahoo": re.compile(r"(^|\.)yahoo\.(com|fr)$", re.IGNORECASE),
    "proton": re.compile(r"(^|\.)proton(\.me|mail\.com)$", re.IGNORECASE),
    "orange": re.compile(r"(^|\.)orange\.fr$", re.IGNORECASE),
    "sfr": re.compile(r"(^|\.)sfr\.fr$", re.IGNORECASE),
    "free": re.compile(r"(^|\.)free\.fr$", re.IGNORECASE),
    "laposte": re.compile(r"(^|\.)laposte\.net$", re.IGNORECASE),
    "wanadoo": re.compile(r"(^|\.)wanadoo\.fr$", re.IGNORECASE),
    "gmx": re.compile(r"(^|\.)gmx\.(com|net|de)$", re.IGNORECASE),
    "icloud": re.compile(r"(^|\.)icloud\.com$", re.IGNORECASE),
    "aol": re.compile(r"(^|\.)aol\.com$", re.IGNORECASE),
}

SOURCE_PATTERNS = {
    "LinkedIn": [
        re.compile(r"(?:linkedin|via\s+linkedin)", re.IGNORECASE),
        re.compile(r"(?:message|inmail|profil)\s+(?:linkedin|pr[ée]sent)", re.IGNORECASE),
    ],
    "Formulaire": [
        re.compile(r"(?:formulaire|form|inscription|subscribe|d[ée]sign|demande\s+d['']info)", re.IGNORECASE),
        re.compile(r"(?:subscribe|unsubscribe|opt[\s-]*in|subscribe\s+to)", re.IGNORECASE),
    ],
    "Signature": [
        re.compile(r"(?:cordialement|best\s+regards?|sinc[èe]rement|kind\s+regards?| regards?)", re.IGNORECASE),
        re.compile(r"(?:c[ée]d[ée]s\s+[àa]|sigu[ée]e?|signed\s+by)", re.IGNORECASE),
    ],
    "Newsletter": [
        re.compile(r"(?:newsletter|news\s*letter|bulletin|infolettre)", re.IGNORECASE),
        re.compile(r"(?:newsletter|unsubscribe|d[ée]sabonnement)", re.IGNORECASE),
    ],
    "Facturation": [
        re.compile(r"(?:facture|invoice|billing|paiement|payment|re[çc]u|receipt)", re.IGNORECASE),
    ],
    "Support": [
        re.compile(r"(?:support|helpdesk|help\s+desk|assistance|aide\s+technique)", re.IGNORECASE),
    ],
    "Contact direct": [
        re.compile(r"(?:contact(?:ez|\s+nous)?|e[\s-]*?mail|courriel)", re.IGNORECASE),
    ],
    "Réseau social": [
        re.compile(r"(?:twitter|facebook|instagram|x\.com|tiktok|threads)", re.IGNORECASE),
    ],
    "E-commerce": [
        re.compile(r"(?:commande|order|panier|cart|livraison|shipping|tracking)", re.IGNORECASE),
    ],
}

ACTIVE_INDICATORS = [
    re.compile(r"\b(envoi|envoy[ée]|r[ée]ponse|r[ée]pondre|confirmer|invoice|paiement|commande|contact)\b", re.IGNORECASE),
    re.compile(r"\bRGPD|newsletter|subscribe|inscri|join|rejoindre\b", re.IGNORECASE),
]

IGNORED_DOMAINS = {
    "example.com", "example.org", "example.net",
    "test.com", "test.fr", "domain.com", "email.com",
    "yourdomain.com", "sentry.io", "none", "null",
    "localhost", "localhost.localdomain",
}

FREE_PROVIDER_DOMAINS = {
    "gmail.com", "googlemail.com", "gmail.fr",
    "outlook.com", "outlook.fr", "hotmail.com", "hotmail.fr", "live.com", "live.fr",
    "msn.com", "yahoo.com", "yahoo.fr", "ymail.com",
    "protonmail.com", "proton.me",
    "icloud.com", "me.com", "mac.com", "aol.com",
    "gmx.com", "gmx.net", "gmx.de", "web.de", "mail.com",
    "orange.fr", "sfr.fr", "free.fr", "laposte.net", "wanadoo.fr",
    "mail.ru", "yandex.com", "yandex.ru",
}

BUSINESS_SOURCES = {
    "LinkedIn", "Facturation", "E-commerce", "Support",
    "Formulaire", "Contact direct", "Signature",
}

DISPOSABLE_DOMAINS = {
    "mailinator.com", "10minutemail.com", "guerrillamail.com", "sharklasers.com",
    "trashmail.com", "tempmail.com", "temp-mail.org", "throwawaymail.com",
    "maildrop.cc", "getnada.com", "yopmail.com", "mailnesia.com",
    "dispostable.com", "mintemail.com", "spamgourmet.com", "jetable.org",
    "fakeinbox.com", "emailondeck.com", "dropmail.me", "tmail.io",
    "inboxbear.com", "emailfake.com", "mailowl.org", "tmpmail.org",
    "einex.de", "backmail.de", "mytemp.email", "temp-mail.io",
}

GENERIC_LOCAL_HINTS = (
    "no-reply", "noreply", "no_reply", "notif", "newsletter",
)

_MONTH_NUM = {}
for _num, _names in {
    1: ["janvier"],
    2: ["février", "fevrier"],
    3: ["mars"],
    4: ["avril"],
    5: ["mai"],
    6: ["juin"],
    7: ["juillet"],
    8: ["août", "aout"],
    9: ["septembre"],
    10: ["octobre"],
    11: ["novembre"],
    12: ["décembre", "decembre"],
}.items():
    for _n in _names:
        _MONTH_NUM[_n] = _num

_MONTH_PATTERN = r"\b(" + "|".join(_MONTH_NUM) + r")\b"
_MONTH_YEAR_PATTERN = r"\b(" + "|".join(_MONTH_NUM) + r")\s+(20\d{2})\b"

_FULL_DATE_RE = re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\b")
_ISO_DATE_RE = re.compile(r"\b(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})\b")
_YEAR_RE = re.compile(r"\b(20[2-9][0-9])\b")
_MONTH_YEAR_RE = re.compile(_MONTH_YEAR_PATTERN, re.IGNORECASE)
_MONTH_RE = re.compile(_MONTH_PATTERN, re.IGNORECASE)

_dns_cache: dict = {}


def _raw_dns_check(domain: str, rtype: str) -> bool:
    resolver = dns.resolver.Resolver()
    resolver.timeout = DNS_TIMEOUT
    resolver.lifetime = DNS_TIMEOUT
    try:
        resolver.resolve(domain, rtype)
        return True
    except Exception:
        pass
    # Certains runtimes (Vercel/Lambda) n'exposent pas de résolveur système
    # joignable : repli sur des résolveurs publics.
    resolver.nameservers = ["8.8.8.8", "1.1.1.1"]
    resolver.resolve(domain, rtype)
    return True


def _check_domain(domain: str) -> bool:
    old_timeout = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(DNS_TIMEOUT)
        socket.getaddrinfo(domain, None)
        return True
    except Exception:
        pass
    finally:
        socket.setdefaulttimeout(old_timeout)
    try:
        return _raw_dns_check(domain, "MX")
    except Exception:
        return False


def domain_valid(domain: str) -> bool:
    now = time.monotonic()
    entry = _dns_cache.get(domain)
    if entry and now - entry[1] < DNS_CACHE_TTL:
        return entry[0]
    valid = _check_domain(domain)
    _dns_cache[domain] = (valid, now)
    return valid


def validate_domains(domains) -> set:
    domains = list(set(domains))
    with ThreadPoolExecutor(max_workers=DNS_WORKERS) as executor:
        results = list(executor.map(domain_valid, domains))
    return {d for d, ok in zip(domains, results) if ok}


def correct_typo(domain: str) -> str:
    return REVERSE_TYPO.get(domain, domain)


def detect_source(text, email, context) -> list:
    sources = []
    for name, patterns in SOURCE_PATTERNS.items():
        if any(p.search(context) for p in patterns):
            sources.append(name)
    return sources or ["Non identifié"]


def last_activity_date(context: str) -> Optional[date]:
    if not context:
        return None
    today = date.today()
    candidates: list = []
    masked = context

    for m in _ISO_DATE_RE.finditer(masked):
        try:
            candidates.append(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            continue
        masked = masked.replace(m.group(0), " ")
    for m in _FULL_DATE_RE.finditer(masked):
        try:
            candidates.append(date(int(m.group(3)), int(m.group(2)), int(m.group(1))))
        except ValueError:
            continue
        masked = masked.replace(m.group(0), " ")
    for m in _MONTH_YEAR_RE.finditer(masked):
        try:
            candidates.append(date(int(m.group(2)), _MONTH_NUM[m.group(1).lower()], 15))
        except ValueError:
            continue
        masked = masked.replace(m.group(0), " ")
    for m in _YEAR_RE.finditer(masked):
        try:
            candidates.append(date(int(m.group(1)), 7, 1))
        except ValueError:
            continue
        masked = masked.replace(m.group(0), " ")
    for m in _MONTH_RE.finditer(masked):
        try:
            candidates.append(date(today.year, _MONTH_NUM[m.group(1).lower()], 1))
        except ValueError:
            continue
        masked = masked.replace(m.group(0), " ")

    return max(candidates) if candidates else None


def categorize(context: str) -> str:
    active = any(p.search(context) for p in ACTIVE_INDICATORS)
    ld = last_activity_date(context)
    if ld is not None:
        recente = (date.today() - ld).days <= RECENT_WINDOW_DAYS
    else:
        recente = any(p.search(context) for p in (re.compile(r"\b20(2[0-9])\b"),
                                                  re.compile(r"\b(septembre|octobre|novembre|d[ée]cembre)\b")))
    if recente and active:
        return "active"
    if recente:
        return "recente"
    return "ancienne"


def domain_type(domain: str) -> str:
    return "pro" if domain not in FREE_PROVIDER_DOMAINS else "perso"


def email_audience(email: str) -> str:
    domain = domain_of(email)
    if domain in DISPOSABLE_DOMAINS:
        return "jetable"
    local = (email.split("@")[0] or "").lower()
    bare = re.sub(r"[\W_]+", "", local)
    if bare in {"info", "contact", "bonjour", "hello", "admin", "webmaster",
                "service", "help", "assistance", "direction", "commercial",
                "ventes", "abuse", "postmaster", "presse", "press", "reclamation"}:
        return "generique"
    if bare.startswith(GENERIC_LOCAL_HINTS):
        return "generique"
    return "nominal"


def quality_score(status: str, dtype: str, sources: list, typo_corrected: bool,
                  audience: str = "nominal", days_ago: Optional[int] = None) -> int:
    score = 20
    if status == "active":
        score += 35
    elif status == "recente":
        score += 20
    if dtype == "pro":
        score += 20
    if sources != ["Non identifié"] and any(s in BUSINESS_SOURCES for s in sources):
        score += 15
    if not typo_corrected:
        score += 10
    if audience == "jetable":
        score -= 35
    elif audience == "generique":
        score -= 10
    if days_ago is not None:
        if days_ago <= 30:
            score += 10
        elif days_ago <= 180:
            score += 5
        if days_ago > 730:
            score -= 20
    return max(min(score, 100), 0)


def score_label(score: int) -> str:
    if score >= 75:
        return "chaud"
    if score >= 50:
        return "tiede"
    return "froid"


def score_color(score: int) -> str:
    if score >= 75:
        return "#10b981"
    if score >= 50:
        return "#f59e0b"
    return "#ef4444"


_TOKEN_RE = re.compile(r"\x00M(\d+)\x00")


def protect_emails(text: str):
    matches = list(EMAIL_REGEX.finditer(text))
    emails_by_index = {}
    parts = []
    cursor = 0
    for i, m in enumerate(matches):
        parts.append(text[cursor:m.start()])
        token = f"\x00M{i}\x00"
        parts.append(token)
        emails_by_index[i] = {
            "email": m.group(0).strip("."),
            "start": m.start(),
            "end": m.end(),
            "token": token,
        }
        cursor = m.end()
    parts.append(text[cursor:])
    protected = "".join(parts)
    return protected, emails_by_index


def segment_units(protected: str) -> list:
    raw_parts = re.split(r"(?<=[.!?;\n])\s+", protected)
    units = []
    search_from = 0
    for part in raw_parts:
        part = part.strip()
        if not part:
            continue
        s = protected.find(part, search_from)
        e = s + len(part)
        units.append({
            "start": s,
            "end": e,
            "text": part,
            "tokens": _TOKEN_RE.findall(part),
        })
        search_from = e
    return units


def sentence_context(text: str, email: str):
    protected, emails_by_index = protect_emails(text)
    target = None
    for i, info in emails_by_index.items():
        if info["email"].lower() == email.lower():
            target = i
            break
    if target is None:
        return "", ""
    units = segment_units(protected)
    my_token = emails_by_index[target]["token"]
    for unit in units:
        if my_token in unit["text"]:
            joined_analyse = re.sub(r"\x00M\d+\x00", " ", unit["text"])
            joined_analyse = re.sub(r"\s+", " ", joined_analyse).strip()
            display = re.sub(r"\s+", " ", unit["text"]).strip()
            display = re.sub(r"\x00M\d+\x00", "", display).strip(" .,;")
            return display, joined_analyse
    return "", ""


def domain_of(email: str) -> str:
    return email.split("@")[-1].lower() if "@" in email else ""


def extract(text: str) -> dict:
    emails = set()
    for m in EMAIL_REGEX.finditer(text):
        email = m.group(0).strip(".")
        emails.add(email.lower())

    filtered = [e for e in emails if domain_of(e) not in IGNORED_DOMAINS]

    corrected = []
    for email in filtered:
        d = domain_of(email)
        fixed_d = correct_typo(d)
        fixed_email = f"{email.split('@')[0]}@{fixed_d}" if fixed_d != d else email
        corrected.append((email, fixed_email))

    valid_domains = validate_domains({domain_of(fixed) for _, fixed in corrected})

    stats = Counter()
    stats["invalid"] = 0
    stats["typo_corrected"] = 0
    stats["chaud"] = 0
    stats["tiede"] = 0
    stats["froid"] = 0
    stats["pro"] = 0
    stats["perso"] = 0
    stats["jetable"] = 0
    stats["generique"] = 0
    stats["nominal"] = 0
    results = []
    today = date.today()
    for original, fixed in corrected:
        d = domain_of(fixed)
        was_corrected = original != fixed
        if was_corrected:
            stats["typo_corrected"] += 1

        if d not in valid_domains:
            stats["invalid"] += 1
            continue

        provider = next((k for k, p in PROVIDER_PATTERNS.items() if p.search(d)), "autre")
        display, analyse = sentence_context(text, original)
        sources = detect_source(text, original, analyse)
        status = categorize(analyse or display)
        dtype = domain_type(d)
        audience = email_audience(fixed)
        ld = last_activity_date(analyse or display)
        days_ago = (today - ld).days if ld else None
        score = quality_score(status, dtype, sources, was_corrected, audience, days_ago)
        heat = score_label(score)
        stats[status] += 1
        stats[heat] += 1
        stats[dtype] += 1
        stats[audience] += 1

        results.append({
            "email": fixed,
            "original": original if was_corrected else None,
            "domain": d,
            "domain_type": dtype,
            "provider": provider,
            "audience": audience,
            "status": status,
            "score": score,
            "heat": heat,
            "sources": sources,
            "context": display or None,
            "last_seen": ld.isoformat() if ld else None,
            "dns_ok": True,
            "typo_corrected": was_corrected,
        })

    results.sort(key=lambda r: r["score"], reverse=True)

    return {
        "total": len(results),
        "recentes": stats["recente"],
        "actives": stats["active"],
        "anciennes": stats["ancienne"],
        "invalides": stats["invalid"],
        "typos_corriges": stats["typo_corrected"],
        "chauds": stats["chaud"],
        "tiedes": stats["tiede"],
        "froids": stats["froid"],
        "pros": stats["pro"],
        "persos": stats["perso"],
        "jetables": stats["jetable"],
        "generiques": stats["generique"],
        "nominaux": stats["nominal"],
        "emails": results,
    }