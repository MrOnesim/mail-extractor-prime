import json
import os
import re
import sqlite3
import tempfile
import threading
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional
from unicodedata import category as _ucat, normalize

# Base par défaut :
#  - si DATABASE_URL (Postgres/Neon) est défini  -> stockage persistant serverless
#  - sinon SQLite local (fichier du projet, ou /tmp sur Vercel sans Neon)
DATABASE_URL = os.environ.get("DATABASE_URL") or ""
DB_PATH = os.environ.get("MAILLENS_DB") or (
    os.path.join(tempfile.gettempdir(), "maillens.db")
    if os.environ.get("VERCEL")
    else os.path.join(os.path.dirname(os.path.abspath(__file__)), "maillens.db")
)

_lock = threading.RLock()
_store = None

GENERIC_AUDIENCES = ("generique", "jetable")

_SQLITE_DDL = [
    """
    CREATE TABLE IF NOT EXISTS leads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        person_key TEXT NOT NULL UNIQUE,
        merge_key TEXT,
        kind TEXT,
        canonical_email TEXT NOT NULL,
        emails TEXT NOT NULL DEFAULT '[]',
        first_name TEXT DEFAULT '',
        last_name TEXT DEFAULT '',
        domain TEXT NOT NULL,
        domain_type TEXT DEFAULT 'pro',
        provider TEXT DEFAULT 'autre',
        audience TEXT DEFAULT 'nominal',
        sources TEXT DEFAULT '[]',
        last_seen TEXT,
        score INTEGER DEFAULT 0,
        heat TEXT DEFAULT 'froid',
        status TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        first_scanned TEXT NOT NULL,
        last_scanned TEXT NOT NULL,
        scans INTEGER DEFAULT 1
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_leads_domain ON leads(domain)",
    "CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status)",
    "CREATE INDEX IF NOT EXISTS idx_leads_heat ON leads(heat)",
    "CREATE INDEX IF NOT EXISTS idx_leads_merge ON leads(merge_key)",
]

_PG_DDL = [
    """
    CREATE TABLE IF NOT EXISTS leads (
        id SERIAL PRIMARY KEY,
        person_key TEXT NOT NULL UNIQUE,
        merge_key TEXT,
        kind TEXT,
        canonical_email TEXT NOT NULL,
        emails TEXT NOT NULL DEFAULT '[]',
        first_name TEXT DEFAULT '',
        last_name TEXT DEFAULT '',
        domain TEXT NOT NULL,
        domain_type TEXT DEFAULT 'pro',
        provider TEXT DEFAULT 'autre',
        audience TEXT DEFAULT 'nominal',
        sources TEXT DEFAULT '[]',
        last_seen TEXT,
        score INTEGER DEFAULT 0,
        heat TEXT DEFAULT 'froid',
        status TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        first_scanned TEXT NOT NULL,
        last_scanned TEXT NOT NULL,
        scans INTEGER DEFAULT 1
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_leads_domain ON leads(domain)",
    "CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status)",
    "CREATE INDEX IF NOT EXISTS idx_leads_heat ON leads(heat)",
    "CREATE INDEX IF NOT EXISTS idx_leads_merge ON leads(merge_key)",
]


class _Store:
    """Accès base de données : SQLite local ou Postgres (Neon) via psycopg_pool.

    SQL écrit avec le style SQLite (`?`) ; il est traduit en `%s` pour Postgres.
    """

    def __init__(self, sqlite_path: Optional[str] = None):
        self.pg = bool(DATABASE_URL) and sqlite_path is None
        self.conn = None
        self.pool = None
        if self.pg:
            from psycopg_pool import ConnectionPool

            self.pool = ConnectionPool(
                conninfo=DATABASE_URL, min_size=0, max_size=4, open=False,
                timeout=15, kwargs={"connect_timeout": 10},
            )
            self.pool.open()
        else:
            self.conn = sqlite3.connect(sqlite_path or DB_PATH, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self):
        ddl = _PG_DDL if self.pg else _SQLITE_DDL
        for stmt in ddl:
            if self.pg:
                with self.pool.connection(timeout=15) as conn:
                    conn.execute(stmt)
            else:
                self.conn.execute(stmt)
        if not self.pg:
            self.conn.commit()

    @staticmethod
    def _sql(sql: str) -> str:
        return sql.replace("?", "%s")

    def query(self, sql: str, params=()) -> list:
        if self.pg:
            from psycopg.rows import dict_row

            with self.pool.connection(timeout=15) as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(self._sql(sql), params or None)
                    return [dict(r) for r in cur.fetchall()]
        cur = self.conn.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]

    def query_one(self, sql: str, params=()) -> Optional[dict]:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql: str, params=()) -> int:
        if self.pg:
            with self.pool.connection(timeout=15) as conn:
                with conn.cursor() as cur:
                    cur.execute(self._sql(sql), params or None)
                    return cur.rowcount
        cur = self.conn.execute(sql, params)
        return cur.rowcount

    def commit(self):
        if not self.pg:
            self.conn.commit()

    def close(self):
        if self.pg:
            self.pool.close()
        else:
            self.conn.close()


def init_db(path: str):
    """Force un stockage SQLite au chemin donné (utilisé par les tests)."""
    global _store, DB_PATH
    with _lock:
        close()
        DB_PATH = path
        _store = _Store(sqlite_path=path)


def get_store() -> _Store:
    global _store
    if _store is None:
        with _lock:
            if _store is None:
                _store = _Store()
    return _store


def close():
    global _store
    with _lock:
        if _store is not None:
            _store.close()
            _store = None


def _norm(s: str) -> str:
    s = normalize("NFD", s)
    s = "".join(c for c in s if _ucat(c) != "Mn")
    return s.lower()


def _tokens(local: str) -> list:
    parts = [_norm(x) for x in re.split(r"[.\-_+]+", local) if x]
    parts = [re.sub(r"\d+$", "", x) for x in parts]
    return [x for x in parts if x] or [local]


def _split_concat(token: str, lexicon: set) -> Optional[list]:
    n = len(token)
    if n < 4 or n > 24:
        return None
    for i in range(1, n - 2):
        surname = token[i:]
        if len(surname) >= 3 and surname in lexicon:
            return [token[:i], surname]
    return None


def person_key(email: str, domain: str, lexicon: set, audience: str = "nominal"):
    """Identité d'une adresse : (kind, domain, surname, first).

    kind = 'full' (deux noms, insensible à l'ordre), 'init' (une initiale),
           'single' (nom seul), 'generic'. Surname/first sont normalisés
           (tri alphabétique pour 'full') pour que prénom.nom == nom.prénom.
    """
    if audience in GENERIC_AUDIENCES:
        return ("generic", email, None, None)
    local = (email.split("@")[0] or "").lower()
    tokens = _tokens(local)
    if len(tokens) == 1:
        split = _split_concat(tokens[0], lexicon)
        if split:
            tokens = split
    if len(tokens) >= 2:
        if any(len(t) == 1 for t in tokens):
            one_char = next(t for t in tokens if len(t) == 1)
            surname = next((t for t in tokens if len(t) > 1), one_char)
            return ("init", domain, surname, one_char)
        a, b = min(tokens), max(tokens)
        return ("full", domain, a, b)
    return ("single", domain, tokens[0], None)


def _merge_key(identity) -> str:
    kind, domain, surname, first = identity
    if kind in ("full", "init") and surname:
        return f"{domain}|{surname}|{first[0]}"
    return json.dumps(identity, ensure_ascii=False)


class _UF:
    def __init__(self, n: int):
        self.p = list(range(n))

    def find(self, x: int) -> int:
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: int, b: int):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _row_to_dict(row: dict) -> dict:
    d = dict(row)
    d["emails"] = json.loads(d["emails"])
    d["sources"] = json.loads(d["sources"])
    return d


def _build_lexicon(results: list) -> dict:
    lexicon: dict = {}
    for r in results:
        if r.get("audience") in GENERIC_AUDIENCES:
            continue
        domain = r.get("domain", "")
        local = (r.get("email", "").split("@")[0] or "").lower()
        tokens = _tokens(local)
        if len(tokens) >= 2:
            lexicon.setdefault(domain, set()).update(t for t in tokens if len(t) >= 2)
    return lexicon


def _component_to_lead(members, audiences) -> dict:
    identified = [m["identity"] for m in members if m["identity"][0] in ("full", "init")]
    best = max(members, key=lambda m: len(m["local"]))
    first, last = "", ""
    canonical = best["email"]
    if identified:
        pool = [i for i in identified if i[0] == "full"] or identified
        top = max(pool, key=lambda i: len(i[3]))
        first, last = top[3], top[2]
        names = {i[3] for i in identified if i[0] == "full"} | {i[2] for i in identified}
        canonical = max(
            (m["email"] for m in members if m["identity"][2] in names or m["identity"][1] == top[1]),
            key=lambda e: len(e.split("@")[0]),
            default=best["email"],
        )
    else:
        first = members[0]["identity"][2]
    return {
        "person_key": best["identity"],
        "merge_key": _merge_key(best["identity"]),
        "kind": best["identity"][0],
        "canonical_email": canonical,
        "emails": sorted({m["email"] for m in members}),
        "first_name": first,
        "last_name": last,
        "domain": best["domain"],
        "domain_type": best["domain_type"],
        "provider": best["provider"],
        "audience": max(audiences, key=lambda a: {"nominal": 2, "generique": 1, "jetable": 0}[a]),
        "sources": sorted({s for m in members for s in m["sources"]}),
        "last_seen": max((m["last_seen"] for m in members if m["last_seen"]), default=None),
        "score": max(m["score"] for m in members),
        "heat": best["heat"],
    }


def merge_analysis(results: list) -> dict:
    db = get_store()
    created = 0
    updated = 0
    now = _now_iso()
    lexicon = _build_lexicon(results)

    members = []
    for r in results:
        email = r.get("email", "")
        domain = r.get("domain", "")
        local = (email.split("@")[0] or "").lower()
        members.append({
            "email": email,
            "local": local,
            "domain": domain,
            "domain_type": r.get("domain_type", "pro"),
            "provider": r.get("provider", "autre"),
            "audience": r.get("audience", "nominal"),
            "sources": set(r.get("sources") or []),
            "last_seen": r.get("last_seen"),
            "score": r.get("score", 0),
            "heat": r.get("heat", "froid"),
            "identity": person_key(email, domain, lexicon.get(domain, set()), r.get("audience", "nominal")),
        })

    n = len(members)
    if n == 0:
        return {"created": 0, "updated": 0}
    uf = _UF(n)

    full_idx: dict = defaultdict(list)
    single_idx: dict = defaultdict(list)
    init_idx: dict = defaultdict(list)
    for i, m in enumerate(members):
        kind, domain, surname, first = m["identity"]
        if kind == "full":
            full_idx[(domain, surname, first)].append(i)
        elif kind == "init":
            init_idx[(domain, surname, first)].append(i)
        elif kind == "single":
            single_idx[(domain, surname, first)].append(i)

    for idxs in full_idx.values():
        base = idxs[0]
        for i in idxs[1:]:
            uf.union(base, i)
    for idxs in single_idx.values():
        base = idxs[0]
        for i in idxs[1:]:
            uf.union(base, i)

    full_by_surname: dict = defaultdict(list)
    for key, idxs in full_idx.items():
        domain, surname, first = key
        full_by_surname[(domain, surname)].append((first, idxs[0]))
    init_categories: dict = defaultdict(list)
    for key, idxs in init_idx.items():
        domain, surname, first = key
        init_categories[(domain, surname, first)].extend(idxs)
    for (domain, surname, char), idxs in init_categories.items():
        cands = {fi: i for fi, i in full_by_surname.get((domain, surname), [])
                 if fi[0] == char}
        if len(cands) > 1:
            cands = dict(list(cands.items())[:1])
        for i in idxs[1:]:
            uf.union(idxs[0], i)
        if cands:
            uf.union(idxs[0], list(cands.values())[0])

    components: dict = defaultdict(list)
    for i, m in enumerate(members):
        components[uf.find(i)].append(i)

    with _lock:
        for root, idxs in components.items():
            group = [members[i] for i in idxs]
            lead = _component_to_lead(group, [m["audience"] for m in group])
            pk = json.dumps(lead["person_key"], ensure_ascii=False)
            mk = lead["merge_key"]
            row = db.query_one("SELECT * FROM leads WHERE person_key = ?", (pk,))
            if row is None and lead["kind"] in ("full", "init"):
                row = db.query_one(
                    "SELECT * FROM leads WHERE merge_key = ? ORDER BY "
                    "CASE kind WHEN 'full' THEN 0 WHEN 'init' THEN 1 ELSE 2 END LIMIT 1",
                    (mk,),
                )

            payload = (
                pk, mk, lead["kind"], lead["canonical_email"],
                json.dumps(lead["emails"], ensure_ascii=False),
                lead["first_name"], lead["last_name"],
                lead["domain"], lead["domain_type"], lead["provider"], lead["audience"],
                json.dumps(lead["sources"], ensure_ascii=False),
                lead["last_seen"], lead["score"], lead["heat"], now, now,
            )
            if row is None:
                db.execute("""
                    INSERT INTO leads (person_key, merge_key, kind, canonical_email, emails,
                                       first_name, last_name, domain, domain_type, provider,
                                       audience, sources, last_seen, score, heat,
                                       first_scanned, last_scanned, scans)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)
                """, payload)
                created += 1
            elif row["person_key"] != pk:
                merged_emails = sorted(set(json.loads(row["emails"]) + lead["emails"]))
                merged_sources = sorted(set(json.loads(row["sources"])) | set(lead["sources"]))
                best = _best_canonical(row["canonical_email"], merged_emails)
                if lead["kind"] == "full" or row["kind"] in ("single", "generic"):
                    new_pk, new_mk, new_kind = pk, mk, lead["kind"]
                    first_name, last_name = lead["first_name"], lead["last_name"]
                else:
                    new_pk, new_mk, new_kind = row["person_key"], row["merge_key"], row["kind"]
                    first_name, last_name = row["first_name"] or "", row["last_name"] or ""
                db.execute("""
                    UPDATE leads SET person_key = ?, merge_key = ?, kind = ?,
                           canonical_email = ?, emails = ?, first_name = ?, last_name = ?,
                           domain_type = ?, provider = ?, audience = ?, sources = ?,
                           last_seen = ?, score = ?, heat = ?, last_scanned = ?,
                           scans = scans + 1
                    WHERE id = ?
                """, (new_pk, new_mk, new_kind, best, json.dumps(merged_emails),
                      first_name, last_name, lead["domain_type"], lead["provider"],
                      lead["audience"], json.dumps(merged_sources),
                      lead["last_seen"] or row["last_seen"],
                      max(row["score"], lead["score"]), lead["heat"], now, row["id"]))
                updated += 1
            else:
                merged_emails = sorted(set(json.loads(row["emails"]) + lead["emails"]))
                merged_sources = sorted(set(json.loads(row["sources"])) | set(lead["sources"]))
                best = _best_canonical(row["canonical_email"], merged_emails)
                db.execute("""
                    UPDATE leads SET canonical_email = ?, emails = ?, sources = ?,
                           last_seen = ?, score = ?, heat = ?, last_scanned = ?,
                           scans = scans + 1
                    WHERE id = ?
                """, (best, json.dumps(merged_emails), json.dumps(merged_sources),
                      lead["last_seen"] or row["last_seen"],
                      max(row["score"], lead["score"]), lead["heat"], now, row["id"]))
                updated += 1
        db.commit()

    return {"created": created, "updated": updated}


def _best_canonical(current: str, emails: list) -> str:
    best = current
    best_len = len(current.split("@")[0])
    for e in emails:
        if len(e.split("@")[0]) > best_len:
            best = e
            best_len = len(e.split("@")[0])
    return best


def list_leads(status: Optional[str] = None, q: Optional[str] = None, limit: int = 500) -> list:
    db = get_store()
    sql = "SELECT * FROM leads"
    clauses = []
    args = []
    if status:
        clauses.append("status = ?")
        args.append(status)
    if q:
        clauses.append(
            "(LOWER(canonical_email) LIKE LOWER(?) OR LOWER(first_name) LIKE LOWER(?) "
            "OR LOWER(last_name) LIKE LOWER(?) OR LOWER(domain) LIKE LOWER(?))"
        )
        like = f"%{q}%"
        args += [like, like, like, like]
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY score DESC, last_seen DESC LIMIT ?"
    args.append(limit)
    return [_row_to_dict(r) for r in db.query(sql, args)]


def get_lead(lead_id: int) -> Optional[dict]:
    db = get_store()
    row = db.query_one("SELECT * FROM leads WHERE id = ?", (lead_id,))
    return _row_to_dict(row) if row else None


def update_lead(lead_id: int, status: Optional[str] = None, notes: Optional[str] = None) -> Optional[dict]:
    db = get_store()
    row = db.query_one("SELECT * FROM leads WHERE id = ?", (lead_id,))
    if row is None:
        return None
    if status is not None:
        db.execute("UPDATE leads SET status = ? WHERE id = ?", (status, lead_id))
    if notes is not None:
        db.execute("UPDATE leads SET notes = ? WHERE id = ?", (notes, lead_id))
    db.commit()
    return get_lead(lead_id)


def delete_lead(lead_id: int) -> bool:
    db = get_store()
    rc = db.execute("DELETE FROM leads WHERE id = ?", (lead_id,))
    db.commit()
    return rc > 0


def stats() -> dict:
    db = get_store()
    rows = db.query("SELECT status, COUNT(*) AS n FROM leads GROUP BY status")
    total = db.query_one("SELECT COUNT(*) AS n FROM leads")["n"]
    return {"total": total, "by_status": {r["status"] or "": r["n"] for r in rows}}


def dashboard() -> dict:
    db = get_store()
    s = stats()
    par_heat = {
        r["heat"] or "froid": r["n"]
        for r in db.query("SELECT heat, COUNT(*) AS n FROM leads GROUP BY heat")
    }
    par_type = {
        r["domain_type"] or "pro": r["n"]
        for r in db.query("SELECT domain_type, COUNT(*) AS n FROM leads GROUP BY domain_type")
    }
    top_domaines = [
        {"domain": r["domain"], "count": r["n"], "max_score": r["m"]}
        for r in db.query(
            "SELECT domain, COUNT(*) AS n, MAX(score) AS m FROM leads "
            "GROUP BY domain ORDER BY n DESC, m DESC LIMIT 8"
        )
    ]
    source_counts: dict = {}
    for r in db.query("SELECT sources FROM leads"):
        for src in json.loads(r["sources"]):
            if src:
                source_counts[src] = source_counts.get(src, 0) + 1
    top_sources = sorted(source_counts.items(), key=lambda kv: kv[1], reverse=True)[:6]
    timeline = [
        {"label": r["d"], "count": r["n"]}
        for r in db.query(
            "SELECT substr(first_scanned, 1, 10) AS d, COUNT(*) AS n FROM leads "
            "GROUP BY substr(first_scanned, 1, 10) ORDER BY d DESC LIMIT 14"
        )
    ]
    timeline.reverse()
    cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    nouveaux = db.query_one(
        "SELECT COUNT(*) AS n FROM leads WHERE substr(first_scanned, 1, 10) >= ?",
        (cutoff,),
    )["n"]
    non_status = db.query_one("SELECT COUNT(*) AS n FROM leads WHERE status = ''")["n"]
    scans_total = db.query_one("SELECT COALESCE(SUM(scans), 0) AS n FROM leads")["n"]
    domains_total = db.query_one("SELECT COUNT(DISTINCT domain) AS n FROM leads")["n"]
    return {
        "total": s["total"],
        "nouveaux_30j": nouveaux,
        "sans_statut": non_status,
        "scans_total": scans_total,
        "domaines_total": domains_total,
        "par_statut": s["by_status"],
        "par_heat": par_heat,
        "par_type_domaine": par_type,
        "top_domaines": top_domaines,
        "top_sources": [{"source": k, "count": v} for k, v in top_sources],
        "timeline": timeline,
    }