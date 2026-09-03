#!/usr/bin/env python3
"""
iitk_kg.py - build the IITK recruiter knowledge graph.

Pipeline:  build   (or: init -> seed -> fetch -> ingest -> review -> report/export)

Privacy contract (non-negotiable, enforced in code):
  * name / email / roll_no are dropped inside the parser and never written to disk,
    logs, or the database. Department ids are retained (branch mix is a real signal)
    but only ever as aggregate counts, and display views suppress cells below K_ANON.
  * No per-student row is ever stored. Records are counted into aggregates and
    the intermediate list is discarded.
  * Display views suppress cells below K_ANON (default 5).

Stdlib only. Python 3.9+.
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import sys
import unicodedata
from difflib import SequenceMatcher
from urllib.request import Request, urlopen

DEFAULT_URL = "https://iitk-spo26.netlify.app/data/stats.json"
DEFAULT_DB = "iitk_kg.sqlite"
K_ANON = 5

# Fields that must never reach storage. Enforced in _strip_pii.
PII_FIELDS = ("name", "email", "roll_no", "id")

ROLES = ("SDE", "QUANT", "ANALYST", "CONSULT", "CORE")

# IITK roll numbers: UG is exactly 6 digits (220954); PG is 9 (241110035, 218070963).
# Only the DIGIT COUNT is read; the gate below then discards the value, so nothing
# identifying is stored. Anything that is not exactly 6 digits is excluded.
UG_ROLL_DIGITS = 6


def is_ug(roll):
    d = "".join(ch for ch in str(roll or "") if ch.isdigit())
    return len(d) == UG_ROLL_DIGITS

# --------------------------------------------------------------------------
# schema
# --------------------------------------------------------------------------

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS company (
    id            TEXT PRIMARY KEY,
    display_name  TEXT NOT NULL,
    canonical_key TEXT NOT NULL,
    category      TEXT,
    hq_region     TEXT,
    origin        TEXT NOT NULL,          -- curated | observed
    recruiting_mode TEXT,                  -- PPO_DOMINANT | CAMPUS_OFFER | BOTH
    note          TEXT,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_company_key ON company(canonical_key);

CREATE TABLE IF NOT EXISTS company_alias (
    company_id TEXT NOT NULL REFERENCES company(id) ON DELETE CASCADE,
    alias      TEXT NOT NULL,
    alias_key  TEXT NOT NULL,
    source     TEXT NOT NULL,             -- seed | spo_observed | manual_review
    PRIMARY KEY (company_id, alias_key)
);
CREATE INDEX IF NOT EXISTS ix_alias_key ON company_alias(alias_key);

-- edge_type is load-bearing:
--   recruits  = this firm hires for this role at IITK -> drives campus recommendations
--   pedigree  = experience HERE is a signal when APPLYING for this role -> scores work
--               experience only, and is NEVER shown as a campus recommendation.
CREATE TABLE IF NOT EXISTS company_role_tier (
    company_id TEXT NOT NULL REFERENCES company(id) ON DELETE CASCADE,
    role       TEXT NOT NULL,
    edge_type  TEXT NOT NULL DEFAULT 'recruits',
    tier       INTEGER,                   -- 1..4, NULL = TIER_UNKNOWN
    source     TEXT NOT NULL,
    PRIMARY KEY (company_id, role, edge_type)
);

CREATE TABLE IF NOT EXISTS desk (
    id         TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES company(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    UNIQUE (company_id, name)
);

CREATE TABLE IF NOT EXISTS role_opening (
    id           TEXT PRIMARY KEY,
    company_id   TEXT NOT NULL REFERENCES company(id) ON DELETE CASCADE,
    desk_id      TEXT REFERENCES desk(id),
    role         TEXT NOT NULL,           -- one of ROLES or UNCLASSIFIED
    profile_raw  TEXT NOT NULL,
    cycle        TEXT NOT NULL,
    UNIQUE (company_id, profile_raw, cycle)
);
CREATE INDEX IF NOT EXISTS ix_opening_role ON role_opening(role, cycle);

-- AGGREGATE ONLY. One row per (opening, department, cycle). Never per student.
-- Department is retained because branch mix per company is a real signal: a firm
-- taking overwhelmingly from one department tells a candidate from elsewhere
-- something the role-level branch rule does not. It is EVIDENCE, never a gate -
-- render it as observed history, not as a criterion the candidate fails.
CREATE TABLE IF NOT EXISTS placement_agg (
    opening_id     TEXT NOT NULL REFERENCES role_opening(id) ON DELETE CASCADE,
    spo_dept_id    INTEGER NOT NULL,
    cycle          TEXT NOT NULL,
    n_recruited    INTEGER NOT NULL DEFAULT 0,
    n_ppo          INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (opening_id, spo_dept_id, cycle)
);

-- Controlled vocabulary from IITK Courses of Study 2021. Independent of SPO ids.
CREATE TABLE IF NOT EXISTS department (
    code   TEXT PRIMARY KEY,
    name   TEXT NOT NULL,
    kind   TEXT,
    source TEXT
);

CREATE TABLE IF NOT EXISTS program (
    code  TEXT PRIMARY KEY,
    name  TEXT NOT NULL,
    level TEXT
);

-- The join SPO does not publish. Fill from the SPO site's own branch labels;
-- unmapped ids still aggregate, they just render as the bare id.
CREATE TABLE IF NOT EXISTS spo_dept_map (
    spo_dept_id  INTEGER PRIMARY KEY,
    dept_code    TEXT REFERENCES department(code),
    program_code TEXT REFERENCES program(code),
    source       TEXT
);

CREATE TABLE IF NOT EXISTS department_cycle_stats (
    spo_dept_id INTEGER NOT NULL,
    cycle       TEXT NOT NULL,
    total       INTEGER,
    pre_offer   INTEGER,
    recruited   INTEGER,
    PRIMARY KEY (spo_dept_id, cycle)
);

CREATE TABLE IF NOT EXISTS institution (
    id           TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    kind         TEXT,
    tier         INTEGER,
    region       TEXT,
    roles        TEXT
);

CREATE TABLE IF NOT EXISTS institution_alias (
    institution_id TEXT NOT NULL REFERENCES institution(id) ON DELETE CASCADE,
    alias_key      TEXT NOT NULL,
    alias          TEXT NOT NULL,
    PRIMARY KEY (institution_id, alias_key)
);

CREATE TABLE IF NOT EXISTS resolution_review (
    raw_name     TEXT PRIMARY KEY,
    raw_key      TEXT NOT NULL,
    candidate_id TEXT,
    score        REAL,
    status       TEXT NOT NULL DEFAULT 'pending',  -- pending | accepted | rejected
    decided_at   TEXT
);

CREATE TABLE IF NOT EXISTS profile_classification (
    profile_key TEXT PRIMARY KEY,
    profile_raw TEXT NOT NULL,
    role        TEXT NOT NULL,
    method      TEXT NOT NULL,            -- rule | desk | manual | unclassified
    confidence  REAL
);

CREATE TABLE IF NOT EXISTS ingest_run (
    id          TEXT PRIMARY KEY,
    source_url  TEXT,
    source_sha  TEXT,
    cycle       TEXT,
    fetched_at  TEXT,
    n_records   INTEGER
);

"""


# --------------------------------------------------------------------------
# normalisation / entity resolution
# --------------------------------------------------------------------------

LEGAL_SUFFIXES = [
    "private limited", "pvt. ltd.", "pvt ltd", "pvt. ltd", "p ltd",
    "limited", "ltd.", "ltd", "llp", "llc", "inc.", "inc", "corp.", "corp",
    "co.", "gmbh", "plc", "s.a.", "sa", "b.v.", "bv", "ag", "and company",
    "& company", "company", "solutions", "services", "technologies",
    "technology", "india", "global tech india",
]

LOCATION_TOKENS = [
    "bangalore", "bengaluru", "noida", "delhi", "new delhi", "mumbai", "pune",
    "hyderabad", "chennai", "gurgaon", "gurugram", "kolkata", "jamshedpur",
    "jamnagar", "ahmedabad", "kanpur",
]


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"')
    return s


def canonical_key(name: str) -> str:
    """Aggressive fold used only for matching. Display name is preserved elsewhere."""
    s = _fold(name or "").lower().strip()
    # strip parentheticals (former names, qualifiers)
    s = re.sub(r"\(([^)]*)\)", " ", s)
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    # location suffix: "citi bank bangalore" -> "citi bank"
    for loc in LOCATION_TOKENS:
        if s.endswith(" " + loc):
            s = s[: -(len(loc) + 1)].strip()
    # legal suffixes, repeatedly (handles "solutions pvt ltd")
    changed = True
    while changed:
        changed = False
        for suf in LEGAL_SUFFIXES:
            sk = re.sub(r"[^a-z0-9]+", " ", suf).strip()
            if s.endswith(" " + sk) and len(s) > len(sk) + 2:
                s = s[: -(len(sk) + 1)].strip()
                changed = True
    return re.sub(r"\s+", " ", s).strip()


def parenthetical_aliases(name: str):
    out = []
    for m in re.finditer(r"\(([^)]*)\)", name or ""):
        inner = m.group(1)
        inner = re.sub(r"(?i)formerly known as", "", inner).strip(" .,")
        if len(inner) > 2:
            out.append(inner)
    return out


def split_joint(name: str):
    """'A Limited & B Limited' -> ['A Limited', 'B Limited'] when both sides look like firms."""
    parts = re.split(r"\s+&\s+|\s+and\s+", name or "")
    if len(parts) == 2 and all(len(p.split()) >= 2 for p in parts):
        return [p.strip() for p in parts]
    return [name]


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ta, tb = set(a.split()), set(b.split())
    jac = len(ta & tb) / len(ta | tb) if (ta | tb) else 0.0
    seq = SequenceMatcher(None, a, b).ratio()
    return max(jac, seq) if (ta & tb) else seq * 0.9


AUTO_MERGE = 0.93
REVIEW_LOW = 0.78


# --------------------------------------------------------------------------
# role classification
# --------------------------------------------------------------------------

ROLE_RULES = [
    ("QUANT", [
        r"\bquant", r"\bquantitative\b", r"\btrader\b", r"\btrading\b",
        r"\bdesk quant\b", r"\bstrats?\b", r"\bhft\b", r"\bmarket mak",
    ]),
    ("SDE", [
        r"\bsde\b", r"\bsoftware (engineer|develop|development)", r"\bswe\b",
        r"\bbackend\b", r"\bfrontend\b", r"\bfull ?stack\b", r"\bplatform engineer\b",
        r"\bapplication developer\b", r"\bfirmware\b", r"\bmember of technical staff\b",
        r"\bmts\b", r"\bdeveloper\b", r"\bprogrammer\b", r"\bverification engineer\b",
        r"\bcloud\b", r"\bdevops\b", r"\bmlops\b", r"\bsre\b",
        r"\binfrastructure\b", r"\bsecurity (platform|researcher)\b",
        r"\brtl design\b", r"\bsoftware\b",
    ]),
    ("ANALYST", [
        r"\bdata scien", r"\bdata engineer\b", r"\bmachine learning\b", r"\bml engineer\b",
        r"\bai engineer\b", r"\bapplied scien", r"\bdecision scien", r"\banalytics\b",
        r"\bbusiness analyst\b", r"\bproduct analyst\b", r"\bdata analyst\b",
        r"\bresearch (scientist|engineer)\b", r"\bstatistic",
    ]),
    ("CONSULT", [
        r"\bconsultant\b", r"\bconsulting\b", r"\bstrategy\b", r"\bs&c\b",
        r"\bmanagement trainee\b", r"\bassociate consultant\b", r"\bproduct manager\b",
        r"\bapm\b", r"\bbusiness (management|track)\b", r"\bgrowth\b",
    ]),
    ("CORE", [
        r"\bmechanical\b", r"\belectrical\b", r"\bchemical\b", r"\bstructural\b",
        r"\bdesign engineer\b", r"\bgraduate engineer(ing)? trainee\b", r"\bget\b",
        r"\bpost ?graduate engineer trainee\b", r"\bfield engineer\b", r"\bplant\b",
        r"\bmanufactur", r"\bsupply chain\b", r"\boperations engineer\b",
        r"\banalog engineer\b", r"\bhardware\b", r"\bembedded\b", r"\bpower engineer",
        r"\bprobationary engineer\b", r"\bcae\b", r"\bcfd\b", r"\bmetallurg",
        r"\btrainee engineer\b", r"\bapplications engineer\b", r"\bsignal processing\b",
    ]),
]

# Build-and-ship markers. When one of these appears the role is SDE even if the title
# also mentions AI or ML - "Gen AI Developer" builds product, "ML Engineer" builds
# models. Note that a bare "engineer" is NOT here: it is too generic to decide on.
DEV_MARKERS = [
    r"\bdeveloper\b", r"\bdev\b", r"\bsde\b", r"\bswe\b",
    r"\bsoftware (engineer|develop)", r"\bfull ?stack\b", r"\bbackend\b",
    r"\bfrontend\b", r"\bweb\b", r"\bmobile\b", r"\bandroid\b", r"\bios\b",
    r"\bplatform engineer\b", r"\bmlops\b", r"\bdevops\b", r"\bsre\b",
    r"\binfrastructure\b", r"\bapplication (developer|engineer)\b",
    r"\bmember of technical staff\b", r"\bprogrammer\b",
]

# Data & AI research / modelling / analytics is an ANALYST domain. A title carrying one
# of these AND no DEV_MARKER goes to ANALYST even when it says "engineer" or
# "consultant" - those are format words; the domain token is the function.
DATA_AI_TOKENS = [
    r"\bdata scien", r"\bdata engineer", r"\bdata analy", r"\bdata platform\b",
    r"\bdata (&|and) ai\b", r"\bdata\b.*\bai\b", r"\bdata mining\b", r"\bdata warehous",
    r"\bmachine learning\b", r"\bdeep learning\b", r"\bml\b", r"\bmlops\b",
    r"\bai\b", r"\ba\.i\.", r"\bartificial intelligence\b",
    r"\bgen ?ai\b", r"\bgenerative ai\b", r"\bllm\b",
    r"\bnlp\b", r"\bnatural language\b", r"\bcomputer vision\b",
    r"\banalytics\b", r"\bbusiness intelligence\b",
    r"\bbi (analyst|developer|engineer|specialist)\b",
    r"\bapplied scien", r"\bdecision scien", r"\bstatistic",
    r"\bforecasting\b", r"\brecommendation system", r"\binsights? analyst\b",
    r"\bresearch (scientist|engineer|associate|analyst)\b", r"\bresearcher\b",
    r"\bscientist\b", r"\bmodel(l)?ing\b", r"\bquantitative analytics\b",
]

# Look data-ish, are not Data/AI functions.
DATA_AI_EXCLUDE = [
    r"\bdatabase\b", r"\bdata cent(er|re)\b", r"\bdata entry\b",
    r"\bdata protection\b", r"\bdata privacy\b",
]

# Seniority / band words that carry no functional meaning on their own.
NOISE_PROFILE = {
    "", ".", "-", "na", "n/a", "pio-ppo", "ppo", "trainee", "associate",
    "manager", "manager -1", "manager-1", "analyst", "senior manager",
    "executive", "graduate trainee", "engineer",
}


def profile_key(p: str) -> str:
    return re.sub(r"\s+", " ", _fold(p or "").lower().strip(" .-\n\t"))


def classify_profile(profile: str, company_hint: str = ""):
    """Return (role, method, confidence). Never guesses on ambiguous strings."""
    key = profile_key(profile)
    if key in NOISE_PROFILE:
        return "UNCLASSIFIED", "unclassified", 0.0
    # QUANT is checked first: a quant desk doing ML is still QUANT.
    quant_hit = any(re.search(p, key) for p in dict(ROLE_RULES)["QUANT"])

    dev_hit = any(re.search(p, key) for p in DEV_MARKERS)

    if not quant_hit and not dev_hit \
            and any(re.search(p, key) for p in DATA_AI_TOKENS) \
            and not any(re.search(p, key) for p in DATA_AI_EXCLUDE):
        return "ANALYST", "data_ai_domain", 0.85

    hits = []
    for role, pats in ROLE_RULES:
        for pat in pats:
            if re.search(pat, key):
                hits.append(role)
                break
    if len(hits) == 1:
        return hits[0], "rule", 0.9
    if len(hits) > 1:
        # an explicit build-and-ship marker settles it: "Software Engineer - ML" is SDE
        if dev_hit and "SDE" in hits:
            return "SDE", "dev_marker", 0.8
        # otherwise the most specific function wins over generic ones
        for role in ("QUANT", "ANALYST", "CONSULT", "SDE", "CORE"):
            if role in hits:
                return role, "rule_priority", 0.65
    if company_hint:
        ck = profile_key(company_hint)
        if any(re.search(p, ck) for p in DATA_AI_TOKENS):
            return "ANALYST", "desk_data_ai", 0.6
        if "research" in ck or "labs" in ck:
            return "ANALYST", "desk", 0.4
    return "UNCLASSIFIED", "unclassified", 0.0


# --------------------------------------------------------------------------
# db helpers
# --------------------------------------------------------------------------

def connect(path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def slug(s):
    return re.sub(r"[^A-Z0-9]+", "_", (s or "").upper()).strip("_")[:48]


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

def cmd_init(args):
    con = connect(args.db)
    con.executescript(SCHEMA)
    con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version','1.0')")
    con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('k_anon',?)", (str(K_ANON),))
    con.commit()
    print(f"initialised {args.db}")


def cmd_seed(args):
    con = connect(args.db)
    n_c = n_a = n_t = 0

    with open(args.companies, encoding="utf-8") as f:
        data = json.load(f)
    for c in data["companies"]:
        con.execute(
            "INSERT OR REPLACE INTO company(id,display_name,canonical_key,category,hq_region,"
            "origin,recruiting_mode,note,created_at) VALUES(?,?,?,?,?,'curated',?,?,?)",
            (c["id"], c["display_name"], canonical_key(c["display_name"]),
             c.get("category"), c.get("hq_region"), c.get("recruiting_mode"),
             c.get("note"), now()))
        n_c += 1
        names = [c["display_name"]] + c.get("aliases", [])
        for a in names:
            con.execute(
                "INSERT OR IGNORE INTO company_alias(company_id,alias,alias_key,source) VALUES(?,?,?,'seed')",
                (c["id"], a, canonical_key(a)))
            n_a += 1
        for edge, field in (("recruits", "recruits_for"), ("pedigree", "pedigree_for")):
            for role, meta in c.get(field, {}).items():
                con.execute(
                    "INSERT OR REPLACE INTO company_role_tier(company_id,role,edge_type,tier,source)"
                    " VALUES(?,?,?,?,?)",
                    (c["id"], role, edge, meta.get("tier"), meta.get("source", "curated")))
                n_t += 1

    n_d = n_p = 0
    if args.departments and os.path.exists(args.departments):
        with open(args.departments, encoding="utf-8") as f:
            dd = json.load(f)
        for d in dd["departments"]:
            con.execute("INSERT OR REPLACE INTO department(code,name,kind,source) VALUES(?,?,?,?)",
                        (d["code"], d["name"], d.get("kind"), d.get("source")))
            n_d += 1
        for p in dd["programs"]:
            con.execute("INSERT OR REPLACE INTO program(code,name,level) VALUES(?,?,?)",
                        (p["code"], p["name"], p.get("level")))
            n_p += 1

    n_i = 0
    if args.institutions and os.path.exists(args.institutions):
        with open(args.institutions, encoding="utf-8") as f:
            idata = json.load(f)
        for i in idata["institutions"]:
            con.execute(
                "INSERT OR REPLACE INTO institution(id,display_name,kind,tier,region,roles) VALUES(?,?,?,?,?,?)",
                (i["id"], i["display_name"], i.get("kind"), i.get("tier"),
                 i.get("region"), json.dumps(i.get("roles", []))))
            for a in [i["display_name"]] + i.get("aliases", []):
                con.execute(
                    "INSERT OR IGNORE INTO institution_alias(institution_id,alias_key,alias) VALUES(?,?,?)",
                    (i["id"], canonical_key(a), a))
            n_i += 1

    con.commit()
    print(f"seeded: {n_c} companies, {n_a} aliases, {n_t} role tiers, "
          f"{n_i} institutions, {n_d} departments, {n_p} programs")


def cmd_fetch(args):
    req = Request(args.url, headers={"User-Agent": "iitk-kg/1.0 (placement research)"})
    with urlopen(req, timeout=60) as r:
        raw = r.read()
    sha = hashlib.sha256(raw).hexdigest()
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "wb") as f:
        f.write(raw)
    # schema drift check
    try:
        d = json.loads(raw)
    except Exception as e:
        print(f"FATAL: response is not JSON: {e}", file=sys.stderr)
        return 2
    missing = [k for k in ("branch", "student") if k not in d]
    if missing:
        print(f"FATAL: expected keys missing: {missing}. Endpoint schema changed; "
              f"keeping previous snapshot and aborting ingest.", file=sys.stderr)
        return 2
    print(f"fetched {len(raw):,} bytes -> {args.out}")
    print(f"sha256  {sha}")
    print(f"records branch={len(d['branch'])} student={len(d['student'])}")
    print("NOTE: this file contains names, emails and roll numbers. "
          "It is a staging artifact only - `ingest` never writes them to the database. "
          "Delete it once ingest completes (`--purge-source`).")
    return 0


def _strip_pii(rec: dict) -> dict:
    """The privacy gate. Returns a record with identifying fields removed."""
    return {k: v for k, v in rec.items() if k not in PII_FIELDS}


def cmd_ingest(args):
    con = connect(args.db)
    with open(args.file, "rb") as f:
        raw = f.read()
    sha = hashlib.sha256(raw).hexdigest()
    data = json.loads(raw)

    if "branch" not in data or "student" not in data:
        print("FATAL: unexpected payload shape", file=sys.stderr)
        return 2

    cycle = args.cycle

    for b in data.get("branch", []):
        # cohort totals from SPO cover UG+PG; they are stored for reference only
        con.execute("INSERT OR REPLACE INTO department_cycle_stats"
                    "(spo_dept_id,cycle,total,pre_offer,recruited) VALUES(?,?,?,?,?)",
                    (b["program_department_id"], cycle, b.get("total"),
                     b.get("pre_offer"), b.get("recruited")))
        con.execute("INSERT OR IGNORE INTO spo_dept_map(spo_dept_id,source) VALUES(?,'unmapped')",
                    (b["program_department_id"],))

    # ---- alias index for resolution ---------------------------------------
    alias_idx = {}
    for r in con.execute("SELECT company_id, alias_key FROM company_alias"):
        alias_idx.setdefault(r["alias_key"], r["company_id"])

    agg = {}          # (company_id, profile_raw, dept) -> counters
    n_pg = 0
    desks = {}        # (company_id, desk_name)
    unresolved = {}
    n_records = 0

    for rec in data["student"]:
        # UG/PG classification reads the roll number's LENGTH only, then the gate
        # below discards the value. Nothing identifying survives this line.
        ug = is_ug(rec.get("roll_no"))
        rec = _strip_pii(rec)              # <-- PII GATE, before anything else
        n_records += 1
        if not args.include_pg and not ug:
            n_pg += 1
            continue

        raw_name = (rec.get("company_name") or "").strip()
        if not raw_name:
            continue
        profile = (rec.get("profile") or "").strip()
        dept = rec.get("program_department_id")
        is_ppo = (rec.get("type") or "").upper().startswith("PIO")

        # --- entity resolution ---
        key = canonical_key(raw_name)
        cid = alias_idx.get(key)
        desk_name = None

        if cid is None:
            # try parenthetical aliases and joint splits
            for cand in parenthetical_aliases(raw_name) + split_joint(raw_name):
                k2 = canonical_key(cand)
                if k2 in alias_idx:
                    cid = alias_idx[k2]
                    break

        if cid is None:
            # fuzzy against known keys
            best, best_score = None, 0.0
            for ak, acid in alias_idx.items():
                s = similarity(key, ak)
                if s > best_score:
                    best, best_score = acid, s
            if best_score >= AUTO_MERGE:
                cid = best
                con.execute("INSERT OR IGNORE INTO company_alias(company_id,alias,alias_key,source)"
                            " VALUES(?,?,?,'spo_observed')", (cid, raw_name, key))
                alias_idx[key] = cid
            elif best_score >= REVIEW_LOW:
                con.execute("INSERT OR IGNORE INTO resolution_review(raw_name,raw_key,candidate_id,score)"
                            " VALUES(?,?,?,?)", (raw_name, key, best, best_score))
                unresolved[raw_name] = best_score
                cid = None
            else:
                cid = None

        if cid is None:
            # create an observed company with no tier (TIER_UNKNOWN)
            cid = "ORG:" + slug(key) or "ORG:UNKNOWN"
            base, n = cid, 1
            while True:
                row = con.execute("SELECT canonical_key FROM company WHERE id=?", (cid,)).fetchone()
                if row is None or row["canonical_key"] == key:
                    break
                n += 1
                cid = f"{base}_{n}"
            con.execute(
                "INSERT OR IGNORE INTO company(id,display_name,canonical_key,category,hq_region,origin,created_at)"
                " VALUES(?,?,?,NULL,NULL,'observed',?)", (cid, raw_name, key, now()))
            con.execute("INSERT OR IGNORE INTO company_alias(company_id,alias,alias_key,source)"
                        " VALUES(?,?,?,'spo_observed')", (cid, raw_name, key))
            alias_idx[key] = cid

        # --- desk detection: unit qualifier after a dash on a known company ---
        m = re.search(r"[-–]\s*([A-Za-z][A-Za-z &]{2,30})$", raw_name)
        if m:
            desk_name = m.group(1).strip()
            desks[(cid, desk_name)] = True

        agg_key = (cid, profile, dept, desk_name)
        d = agg.setdefault(agg_key, {"rec": 0, "ppo": 0})
        if is_ppo:
            d["ppo"] += 1
        else:
            d["rec"] += 1

    # data["student"] goes out of scope here; nothing per-person is retained.
    del data

    # ---- write desks ------------------------------------------------------
    for (cid, dname) in desks:
        did = f"DESK:{slug(cid)}:{slug(dname)}"
        con.execute("INSERT OR IGNORE INTO desk(id,company_id,name) VALUES(?,?,?)", (did, cid, dname))

    # ---- write openings + aggregates --------------------------------------
    n_open = 0
    for (cid, profile, dept, desk_name), counts in agg.items():
        pkey = profile_key(profile)
        row = con.execute("SELECT role FROM profile_classification WHERE profile_key=?", (pkey,)).fetchone()
        if row:
            role = row["role"]
        else:
            role, method, conf = classify_profile(profile, desk_name or "")
            con.execute("INSERT OR REPLACE INTO profile_classification"
                        "(profile_key,profile_raw,role,method,confidence) VALUES(?,?,?,?,?)",
                        (pkey, profile, role, method, conf))

        # PPO rows often carry no job title at all - the profile field is literally
        # "PIO-PPO" or blank. The title cannot decide the role, but the company can:
        # if the firm is curated with exactly ONE recruiting role, attribute it there.
        # Deliberately NOT cached in profile_classification, which is keyed on the
        # title alone and would otherwise leak one company's role onto every other
        # company using the same placeholder.
        if role == "UNCLASSIFIED" and pkey in NOISE_PROFILE:
            cand = [r["role"] for r in con.execute(
                "SELECT role FROM company_role_tier WHERE company_id=? AND edge_type='recruits'",
                (cid,))]
            if len(cand) == 1:
                role = cand[0]

        oid = f"OPEN:{slug(cid)}:{slug(pkey)[:24]}:{cycle}"
        desk_id = f"DESK:{slug(cid)}:{slug(desk_name)}" if desk_name else None
        con.execute("INSERT OR IGNORE INTO role_opening(id,company_id,desk_id,role,profile_raw,cycle)"
                    " VALUES(?,?,?,?,?,?)", (oid, cid, desk_id, role, profile, cycle))
        n_open += 1
        con.execute("""INSERT INTO placement_agg
                         (opening_id,spo_dept_id,cycle,n_recruited,n_ppo)
                       VALUES(?,?,?,?,?)
                       ON CONFLICT(opening_id,spo_dept_id,cycle) DO UPDATE SET
                         n_recruited  = n_recruited  + excluded.n_recruited,
                         n_ppo        = n_ppo        + excluded.n_ppo""",
                    (oid, dept, cycle, counts["rec"], counts["ppo"]))

    # tier-unknown rows for observed companies
    con.execute("""INSERT OR IGNORE INTO company_role_tier(company_id,role,edge_type,tier,source)
                   SELECT DISTINCT o.company_id, o.role, 'recruits', NULL, 'tier_unknown'
                   FROM role_opening o
                   WHERE o.role != 'UNCLASSIFIED'
                     AND NOT EXISTS (SELECT 1 FROM company_role_tier t
                                     WHERE t.company_id=o.company_id AND t.role=o.role
                                       AND t.edge_type='recruits')""")

    n_comp = con.execute("SELECT COUNT(*) c FROM company").fetchone()["c"]
    run_id = f"RUN:{cycle}:{sha[:12]}"
    con.execute("INSERT OR REPLACE INTO ingest_run"
                "(id,source_url,source_sha,cycle,fetched_at,n_records) VALUES(?,?,?,?,?,?)",
                (run_id, args.source_url, sha, cycle, now(), n_records))
    con.commit()

    print(f"ingested {n_records} records for cycle {cycle}")
    if n_pg:
        print(f"  excluded         : {n_pg} PG records (9-digit roll) - "
              f"pass --include-pg to keep them")
    print(f"  openings written : {n_open}")
    print(f"  companies total  : {n_comp}")
    print(f"  pending review   : {len(unresolved)}  (run: iitk_kg.py review)")
    unc = con.execute("SELECT COUNT(*) c FROM role_opening WHERE role='UNCLASSIFIED' AND cycle=?",
                      (cycle,)).fetchone()["c"]
    print(f"  unclassified     : {unc} openings (run: iitk_kg.py unmapped)")

    if args.purge_source:
        os.remove(args.file)
        print(f"  purged source    : {args.file}")
    return 0


def cmd_review(args):
    con = connect(args.db)
    if args.accept:
        raw, cid = args.accept.split("=", 1)
        row = con.execute("SELECT raw_key FROM resolution_review WHERE raw_name=?", (raw,)).fetchone()
        if not row:
            print("no such pending item", file=sys.stderr)
            return 1
        con.execute("INSERT OR IGNORE INTO company_alias(company_id,alias,alias_key,source)"
                    " VALUES(?,?,?,'manual_review')", (cid, raw, row["raw_key"]))
        con.execute("UPDATE resolution_review SET status='accepted', candidate_id=?, decided_at=?"
                    " WHERE raw_name=?", (cid, now(), raw))
        con.commit()
        print(f"aliased {raw!r} -> {cid}. Re-run ingest to re-aggregate.")
        return 0
    if args.reject:
        con.execute("UPDATE resolution_review SET status='rejected', decided_at=? WHERE raw_name=?",
                    (now(), args.reject))
        con.commit()
        print("rejected")
        return 0
    rows = con.execute("SELECT r.raw_name, r.candidate_id, r.score, c.display_name"
                       " FROM resolution_review r LEFT JOIN company c ON c.id=r.candidate_id"
                       " WHERE r.status='pending' ORDER BY r.score DESC").fetchall()
    if not rows:
        print("no pending resolution decisions")
        return 0
    print(f"{len(rows)} pending:\n")
    for r in rows:
        print(f"  {r['score']:.2f}  {r['raw_name']!r}")
        print(f"         candidate: {r['candidate_id']} ({r['display_name']})")
        print(f"         accept:  iitk_kg.py review --accept \"{r['raw_name']}={r['candidate_id']}\"")
    return 0


def cmd_unmapped(args):
    con = connect(args.db)
    rows = con.execute("""SELECT p.spo_dept_id, SUM(p.n_recruited+p.n_ppo) n
                          FROM placement_agg p
                          LEFT JOIN spo_dept_map m ON m.spo_dept_id=p.spo_dept_id
                          WHERE m.dept_code IS NULL
                          GROUP BY p.spo_dept_id ORDER BY n DESC""").fetchall()
    if rows:
        print(f"== {len(rows)} observed department ids without a branch mapping ==")
        print("   " + ", ".join(f"{r['spo_dept_id']}(n={r['n']})" for r in rows[:20]))
        print("   Fill dept_map.csv, then: iitk_kg.py deptmap --map dept_map.csv\n")

    print("== companies with no curated tier (TIER_UNKNOWN) ==")
    rows = con.execute("""SELECT c.id, c.display_name, o.role, SUM(p.n_recruited+p.n_ppo) n
                          FROM company c JOIN role_opening o ON o.company_id=c.id
                          JOIN placement_agg p ON p.opening_id=o.id
                          JOIN company_role_tier t ON t.company_id=c.id AND t.role=o.role
                               AND t.edge_type='recruits'
                          WHERE t.tier IS NULL AND o.role!='UNCLASSIFIED'
                          GROUP BY c.id,o.role ORDER BY n DESC LIMIT ?""", (args.limit,)).fetchall()
    for r in rows:
        print(f"  {r['n']:>3}  {r['role']:<12} {r['display_name']}   [{r['id']}]")

    print("\n== unclassified profiles ==")
    rows = con.execute("""SELECT o.profile_raw, c.display_name, SUM(p.n_recruited+p.n_ppo) n
                          FROM role_opening o JOIN company c ON c.id=o.company_id
                          JOIN placement_agg p ON p.opening_id=o.id
                          WHERE o.role='UNCLASSIFIED'
                          GROUP BY o.profile_raw, c.id ORDER BY n DESC LIMIT ?""", (args.limit,)).fetchall()
    for r in rows:
        print(f"  {r['n']:>3}  {r['profile_raw']!r} @ {r['display_name']}")
    return 0


def cmd_build(args):
    """One-shot: init + seed + fetch + ingest + export, then report what needs a human."""
    class A:
        pass

    print("[1/5] schema")
    a = A(); a.db = args.db
    cmd_init(a)

    print("[2/5] curated registry")
    a = A(); a.db = args.db; a.companies = args.companies
    a.institutions = args.institutions; a.departments = args.departments
    cmd_seed(a)

    staging = args.file
    if args.file and os.path.exists(args.file):
        print(f"[3/5] using existing {args.file}")
    else:
        print("[3/5] fetch")
        staging = args.file or "raw/stats.json"
        a = A(); a.db = args.db; a.url = args.url; a.out = staging
        rc = cmd_fetch(a)
        if rc:
            return rc

    print("[4/5] ingest")
    a = A(); a.db = args.db; a.file = staging; a.cycle = args.cycle
    a.source_url = args.url; a.purge_source = args.purge_source
    a.include_pg = args.include_pg
    rc = cmd_ingest(a)
    if rc:
        return rc

    if args.dept_map and os.path.exists(args.dept_map):
        a = A(); a.db = args.db; a.map = args.dept_map
        cmd_deptmap(a)

    print("[5/5] export")
    a = A(); a.db = args.db; a.out = args.out; a.mode = "signals"
    cmd_export(a)

    con = connect(args.db)
    n_rev = con.execute("SELECT COUNT(*) c FROM resolution_review WHERE status='pending'").fetchone()["c"]
    n_unc = con.execute("SELECT COUNT(*) c FROM role_opening WHERE role='UNCLASSIFIED'").fetchone()["c"]
    n_dm = con.execute("""SELECT COUNT(DISTINCT p.spo_dept_id) c FROM placement_agg p
                          LEFT JOIN spo_dept_map m ON m.spo_dept_id=p.spo_dept_id
                          WHERE m.dept_code IS NULL""").fetchone()["c"]
    n_tu = con.execute("""SELECT COUNT(DISTINCT c.id) c FROM company c
                          JOIN company_role_tier t ON t.company_id=c.id AND t.edge_type='recruits'
                          WHERE t.tier IS NULL""").fetchone()["c"]

    print("\n" + "=" * 62)
    print("DATABASE BUILT. It is usable now.")
    print("=" * 62)
    print(f"  {args.db}  ->  {args.out}")
    print("\nOptional quality work, in order of payoff:")
    print(f"  {n_tu:>4} firms have no tier      -> edit companies.seed.json, re-run build")
    print(f"  {n_unc:>4} openings unclassified  -> iitk_kg.py classify --set \"<profile>=<ROLE>\"")
    print(f"  {n_rev:>4} company-name near-miss -> iitk_kg.py review")
    print(f"  {n_dm:>4} observed ids unmapped  -> add rows to dept_map.csv, re-run build")
    print("\nSkipping all of it costs coverage, not correctness: unclassified openings")
    print("are excluded from role counts rather than misfiled, and untiered firms show")
    print("as TIER_UNKNOWN rather than being guessed.")
    print("\nSee what it produced:  python3 iitk_kg.py report")
    return 0


def cmd_classify(args):
    con = connect(args.db)
    raw, role = args.set.split("=", 1)
    role = role.strip().upper()
    if role not in ROLES and role != "UNCLASSIFIED":
        print(f"role must be one of {ROLES} or UNCLASSIFIED", file=sys.stderr)
        return 1
    pkey = profile_key(raw)
    con.execute("INSERT OR REPLACE INTO profile_classification"
                "(profile_key,profile_raw,role,method,confidence) VALUES(?,?,?, 'manual', 1.0)",
                (pkey, raw, role))
    n = con.execute("UPDATE role_opening SET role=? WHERE profile_raw=?", (role, raw)).rowcount
    con.commit()
    print(f"classified {raw!r} -> {role} ({n} openings updated)")
    return 0


def cmd_deptmap(args):
    """Load spo_dept_id -> dept_code,program_code from CSV, with validation."""
    con = connect(args.db)
    n = 0
    seen_pair, errors, warns = {}, [], []
    with open(args.map, encoding="utf-8") as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if not line or line.lower().startswith("spo_dept_id"):
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 2 or not parts[1]:
                continue                       # unfilled scaffold row
            sid = int(parts[0])
            dept = parts[1].upper()
            prog = parts[2].upper() if len(parts) > 2 and parts[2] else None
            if not con.execute("SELECT 1 FROM department WHERE code=?", (dept,)).fetchone():
                errors.append(f"id {sid}: unknown department code {dept!r}")
                continue
            if prog and not con.execute("SELECT 1 FROM program WHERE code=?", (prog,)).fetchone():
                errors.append(f"id {sid}: unknown program code {prog!r}")
                continue
            key = (dept, prog)
            if key in seen_pair:
                warns.append(f"{dept}/{prog or '-'} mapped to BOTH id {seen_pair[key]} and id {sid}")
            else:
                seen_pair[key] = sid
            con.execute("INSERT OR REPLACE INTO spo_dept_map"
                        "(spo_dept_id,dept_code,program_code,source) VALUES(?,?,?,'manual')",
                        (sid, dept, prog))
            n += 1
    con.commit()

    stray = [r["spo_dept_id"] for r in con.execute(
        "SELECT spo_dept_id FROM spo_dept_map WHERE dept_code IS NOT NULL"
        " AND spo_dept_id NOT IN (SELECT DISTINCT spo_dept_id FROM placement_agg)")]
    if len(stray) > 6:
        warns.append(f"{len(stray)} mapped ids have no UG placements in this payload "
                     f"(normal on a partial file)")
    else:
        for sid in stray:
            warns.append(f"id {sid} is mapped but has no UG placements in this payload")

    tot = con.execute("SELECT COALESCE(SUM(n_recruited+n_ppo),0) t FROM placement_agg").fetchone()["t"]
    cov = con.execute("""SELECT COALESCE(SUM(p.n_recruited+p.n_ppo),0) t FROM placement_agg p
                         JOIN spo_dept_map m ON m.spo_dept_id=p.spo_dept_id
                         WHERE m.dept_code IS NOT NULL""").fetchone()["t"]
    unmapped = con.execute("""SELECT COUNT(DISTINCT p.spo_dept_id) c FROM placement_agg p
                              LEFT JOIN spo_dept_map m ON m.spo_dept_id=p.spo_dept_id
                              WHERE m.dept_code IS NULL""").fetchone()["c"]

    print(f"mapped {n} SPO department ids")
    if tot:
        print(f"coverage: {cov}/{tot} placements ({cov/tot:.0%}) sit in a named branch; "
              f"{unmapped} observed ids still unmapped")
    for e in errors:
        print(f"  ERROR  {e}", file=sys.stderr)
    for w in warns:
        print(f"  WARN   {w}", file=sys.stderr)
    if errors:
        print("\n  Rows with errors were skipped. Fix them and re-run.", file=sys.stderr)
    return 0


def cmd_report(args):
    con = connect(args.db)
    q = lambda s, *a: con.execute(s, a).fetchall()
    print("=== IITK recruiter graph ===")
    for r in q("SELECT key,value FROM meta"):
        print(f"  {r['key']}: {r['value']}")
    for r in q("SELECT cycle, n_records, fetched_at FROM ingest_run ORDER BY fetched_at"):
        print(f"  cycle {r['cycle']}: {r['n_records']} records, {r['fetched_at']}")
    print("\n-- companies by origin --")
    for r in q("SELECT origin, COUNT(*) c FROM company GROUP BY origin"):
        print(f"  {r['origin']:<10} {r['c']}")
    print("\n-- openings by role --")
    for r in q("SELECT role, COUNT(*) c, SUM(1) FROM role_opening GROUP BY role ORDER BY c DESC"):
        print(f"  {r['role']:<14} {r['c']}")
    print("\n-- top companies by hires (role-classified only) --")
    for r in q("""SELECT c.display_name, o.role, SUM(p.n_recruited) rec, SUM(p.n_ppo) ppo
                  FROM company c JOIN role_opening o ON o.company_id=c.id
                  JOIN placement_agg p ON p.opening_id=o.id
                  WHERE o.role!='UNCLASSIFIED'
                  GROUP BY c.id,o.role ORDER BY (rec+ppo) DESC LIMIT 15"""):
        print(f"  {r['rec']+r['ppo']:>3} ({r['ppo']} ppo)  {r['role']:<10} {r['display_name']}")
    mapped = q("SELECT COUNT(*) c FROM spo_dept_map WHERE dept_code IS NOT NULL")[0]["c"]
    if mapped:
        print("\n-- top branches by placements (check these look right) --")
        for r in q("""SELECT m.dept_code, m.program_code, SUM(p.n_recruited+p.n_ppo) n
                      FROM placement_agg p
                      JOIN spo_dept_map m ON m.spo_dept_id=p.spo_dept_id
                      WHERE m.dept_code IS NOT NULL
                      GROUP BY m.dept_code, m.program_code ORDER BY n DESC LIMIT 12"""):
            print(f"  {r['n']:>4}  {r['dept_code']}/{r['program_code'] or '-'}")

    print("\n-- curated coverage by role (recruits vs pedigree) --")
    for r in q("""SELECT role, edge_type, COUNT(*) c FROM company_role_tier
                  WHERE source LIKE 'curated%' GROUP BY role,edge_type ORDER BY role"""):
        print(f"  {r['role']:<10} {r['edge_type']:<9} {r['c']}")
    missing = q("""SELECT c.display_name, t.role FROM company c
                   JOIN company_role_tier t ON t.company_id=c.id AND t.edge_type='recruits'
                   WHERE c.recruiting_mode='PPO_DOMINANT'
                     AND NOT EXISTS (SELECT 1 FROM role_opening o WHERE o.company_id=c.id)""")
    if missing:
        print(f"\n-- {len(missing)} PPO-dominant firms absent from placement data (EXPECTED) --")
        for r in missing[:10]:
            print(f"  {r['role']:<8} {r['display_name']}")
        print("  These hire via intern->PPO. Absence here is correct, not missing data;")
        print("  the campus panel must say so rather than render an empty list.")
    unseen = q("""SELECT c.display_name, GROUP_CONCAT(t.role) roles
                  FROM company c
                  JOIN company_role_tier t ON t.company_id=c.id AND t.edge_type='recruits'
                  WHERE c.origin='curated' AND c.recruiting_mode!='PPO_DOMINANT'
                    AND c.id NOT IN (SELECT DISTINCT company_id FROM role_opening)
                  GROUP BY c.id ORDER BY c.display_name""")
    if unseen:
        print(f"\n-- {len(unseen)} curated firms NOT seen recruiting at IITK this cycle --")
        for r in unseen[:25]:
            print(f"  {r['roles']:<16} {r['display_name']}")
        if len(unseen) > 25:
            print(f"  ... and {len(unseen)-25} more")
        print("  These are named in the role frameworks as domain leaders, which is not")
        print("  the same as recruiting here. Exported as iitk_presence=not_observed_at_iitk;")
        print("  do not surface them as campus targets without confirming with SPO.")

    print("\nReminder: hiring volume is NOT a tier signal - it inverts at the top "
          "(mass recruiters hire dozens; the most selective firms hire one or two).")
    return 0


def _shrink(n, k=8):
    """Evidence strength: thin observations self-attenuate toward 0."""
    return round(n / (n + k), 3)


def cmd_export(args):
    """Emit the graph.

    Default mode is 'signals': normalized 0-1 features for ranking, with NO raw
    counts. Nothing that leaves here is a publishable statistic, so nothing needs
    k-anonymity suppression and the dashboard has no placement numbers to render.

    Mode 'raw' includes counts. It is for debugging and curation only - do not ship
    it to a client.
    """
    con = connect(args.db)
    raw = args.mode == "raw"
    out = {"exported_at": now(), "mode": args.mode,
           "kb_version": con.execute("SELECT value FROM meta WHERE key='schema_version'"
                                     ).fetchone()["value"],
           "note": ("Normalized signals for ranking. Values are relative within role, not "
                    "counts. evidence_strength attenuates thin observations - multiply it "
                    "into any weight derived from the observed block."
                    if not raw else "RAW COUNTS - internal use only, do not ship."),
           "companies": []}

    # role-level maxima, for normalizing presence within a role
    peak = {}
    for r in con.execute("""SELECT o.role, MAX(t) m FROM (
                              SELECT o.company_id, o.role, SUM(p.n_recruited+p.n_ppo) t
                              FROM role_opening o JOIN placement_agg p ON p.opening_id=o.id
                              GROUP BY o.company_id, o.role) o GROUP BY o.role"""):
        peak[r["role"]] = r["m"] or 1

    # Which curated firms were actually seen recruiting at IITK. The frameworks list
    # domain leaders globally, not campus recruiters - a firm named there but never
    # observed here is UNVERIFIED and must not be recommended as a campus target.
    seen = {r["company_id"] for r in con.execute(
        "SELECT DISTINCT company_id FROM role_opening")}

    for c in con.execute("SELECT * FROM company ORDER BY display_name"):
        if c["id"] in seen:
            presence = "observed_at_iitk"
        elif c["recruiting_mode"] == "PPO_DOMINANT":
            presence = "ppo_only_expected"      # legitimately absent from offer data
        else:
            presence = "not_observed_at_iitk"   # named in a framework, never seen here
        rec = {"id": c["id"], "display_name": c["display_name"], "category": c["category"],
               "hq_region": c["hq_region"], "origin": c["origin"],
               "recruiting_mode": c["recruiting_mode"],
               "iitk_presence": presence,
               "aliases": [r["alias"] for r in con.execute(
                   "SELECT alias FROM company_alias WHERE company_id=?", (c["id"],))],
               "recruits_for": {}, "pedigree_for": {}}
        desks = [r["name"] for r in con.execute(
            "SELECT name FROM desk WHERE company_id=? ORDER BY name", (c["id"],))]
        if desks:
            rec["desks"] = desks
        for t in con.execute("SELECT role,edge_type,tier,source FROM company_role_tier"
                             " WHERE company_id=?", (c["id"],)):
            bucket = "recruits_for" if t["edge_type"] == "recruits" else "pedigree_for"
            rec[bucket][t["role"]] = {"tier": t["tier"], "source": t["source"]}

        observed = {}
        for o in con.execute("""SELECT o.role, p.cycle, SUM(p.n_recruited) rec, SUM(p.n_ppo) ppo
                                FROM role_opening o JOIN placement_agg p ON p.opening_id=o.id
                                WHERE o.company_id=? AND o.role!='UNCLASSIFIED'
                                GROUP BY o.role,p.cycle""", (c["id"],)):
            n = (o["rec"] or 0) + (o["ppo"] or 0)
            if not n:
                continue
            sig = {
                "observed_recruiting": True,
                "presence_strength": round(min(n / peak.get(o["role"], 1), 1.0), 3),
                "ppo_orientation": round((o["ppo"] or 0) / n, 3),
                "evidence_strength": _shrink(n),
            }
            if raw:
                sig["_n_recruited"], sig["_n_ppo"] = o["rec"], o["ppo"]
            observed.setdefault(o["cycle"], {})[o["role"]] = sig
        if observed:
            rec["observed"] = observed

        # branch affinity: share of this firm's hires from each branch, not counts
        mix = list(con.execute("""SELECT COALESCE(m.dept_code,'SPO_'||p.spo_dept_id) b, m.program_code pr,
                                         SUM(p.n_recruited+p.n_ppo) n
                                  FROM placement_agg p
                                  JOIN role_opening o ON o.id=p.opening_id
                                  LEFT JOIN spo_dept_map m ON m.spo_dept_id=p.spo_dept_id
                                  WHERE o.company_id=? GROUP BY b, m.program_code
                                  ORDER BY n DESC""", (c["id"],)))
        tot = sum(r["n"] for r in mix)
        if tot:
            aff = [{"branch": r["b"], "program": r["pr"],
                    "affinity": round(r["n"] / tot, 3),
                    "resolved": not str(r["b"]).startswith("SPO_")} for r in mix]
            if raw:
                for a, r in zip(aff, mix):
                    a["_n"] = r["n"]
            rec["branch_affinity"] = aff
            rec["branch_concentration"] = aff[0]["affinity"]
            rec["branch_evidence_strength"] = _shrink(tot)
        out["companies"].append(rec)

    # ---- role x branch rollups (institute-level base rates) -------------------
    rb = list(con.execute("""SELECT o.role, COALESCE(m.dept_code,'SPO_'||p.spo_dept_id) b,
                                    m.program_code pr, SUM(p.n_recruited+p.n_ppo) n
                             FROM placement_agg p
                             JOIN role_opening o ON o.id=p.opening_id
                             LEFT JOIN spo_dept_map m ON m.spo_dept_id=p.spo_dept_id
                             WHERE o.role!='UNCLASSIFIED'
                             GROUP BY o.role, b, m.program_code"""))

    by_role, by_branch = {}, {}
    for r in rb:
        by_role.setdefault(r["role"], []).append(r)
        by_branch.setdefault(r["b"], []).append(r)

    out["role_branch_signals"] = {}
    for role, rows in by_role.items():
        tot = sum(x["n"] for x in rows)
        rows = sorted(rows, key=lambda x: -x["n"])
        d = {"branch_affinity": [{"branch": x["b"], "program": x["pr"],
                                  "affinity": round(x["n"] / tot, 3),
                                  "resolved": not str(x["b"]).startswith("SPO_")}
                                 for x in rows],
             "branch_concentration": round(rows[0]["n"] / tot, 3),
             "n_branches": len({x["b"] for x in rows}),
             "evidence_strength": _shrink(tot, k=25)}
        if raw:
            d["_n"] = tot
        out["role_branch_signals"][role] = d

    out["branch_role_signals"] = {}
    for branch, rows in by_branch.items():
        tot = sum(x["n"] for x in rows)
        agg = {}
        for x in rows:
            agg[x["role"]] = agg.get(x["role"], 0) + x["n"]
        ordered = sorted(agg.items(), key=lambda kv: -kv[1])
        d = {"role_affinity": [{"role": k, "affinity": round(v / tot, 3)} for k, v in ordered],
             "dominant_role": ordered[0][0],
             "evidence_strength": _shrink(tot, k=25)}
        if raw:
            d["_n"] = tot
        out["branch_role_signals"][branch] = d

    out["rollup_caveat"] = (
        "role_branch_signals and branch_role_signals are conditioned on PLACEMENT OFFERS "
        "only. Roles that hire mainly through intern-to-PPO conversion - quant above all - "
        "are under-represented, so a thin or skewed quant branch distribution reflects the "
        "hiring channel, not branch preference. Always gate on evidence_strength, and treat "
        "these as observed history, never as eligibility.")

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    n_obs = sum(1 for c in out["companies"] if c.get("observed"))
    from collections import Counter
    pres = Counter(c["iitk_presence"] for c in out["companies"])
    print(f"exported {len(out['companies'])} companies -> {args.out}  (mode={args.mode})")
    print(f"  {n_obs} with observed-recruiting signals")
    print(f"  presence: {pres['observed_at_iitk']} observed at IITK, "
          f"{pres['ppo_only_expected']} PPO-only (expected absent), "
          f"{pres['not_observed_at_iitk']} unverified")
    print(f"  role x branch rollups: {len(out['role_branch_signals'])} roles, "
          f"{len(out['branch_role_signals'])} branches")
    if raw:
        print("  WARNING: raw mode includes counts. Internal use only.")
    return 0


# --------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(prog="iitk_kg.py", description="Build the IITK recruiter knowledge graph.")
    p.add_argument("--db", default=DEFAULT_DB)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("build", help="ONE-SHOT: schema + seed + fetch + ingest + export")
    s.add_argument("--url", default=DEFAULT_URL)
    s.add_argument("--file", default=None, help="use a local payload instead of fetching")
    s.add_argument("--cycle", default="2025-26")
    s.add_argument("--companies", default="companies.seed.json")
    s.add_argument("--institutions", default="institutions.seed.json")
    s.add_argument("--departments", default="departments.seed.json")
    s.add_argument("--dept-map", default="dept_map.csv")
    s.add_argument("--out", default="kg_export.json")
    s.add_argument("--purge-source", action="store_true")
    s.add_argument("--include-pg", action="store_true",
                   help="keep PG cohorts (9-digit roll numbers); excluded by default")
    s.set_defaults(fn=cmd_build)

    s = sub.add_parser("init", help="(advanced) create the database and schema")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("seed", help="(advanced) load the curated company / institution registry")
    s.add_argument("--companies", default="companies.seed.json")
    s.add_argument("--institutions", default="institutions.seed.json")
    s.add_argument("--departments", default="departments.seed.json")
    s.set_defaults(fn=cmd_seed)

    s = sub.add_parser("fetch", help="(advanced) download the SPO stats payload to a staging file")
    s.add_argument("--url", default=DEFAULT_URL)
    s.add_argument("--out", default="raw/stats.json")
    s.set_defaults(fn=cmd_fetch)

    s = sub.add_parser("ingest", help="(advanced) privacy-gate, resolve, classify and aggregate into the graph")
    s.add_argument("--file", default="raw/stats.json")
    s.add_argument("--cycle", required=True, help="e.g. 2025-26")
    s.add_argument("--source-url", default=DEFAULT_URL)
    s.add_argument("--purge-source", action="store_true", help="delete the staging file after ingest")
    s.add_argument("--include-pg", action="store_true",
                   help="keep PG cohorts (9-digit roll numbers); excluded by default")
    s.set_defaults(fn=cmd_ingest)

    s = sub.add_parser("review", help="entity-resolution decisions needing a human")
    s.add_argument("--accept", metavar="RAW=COMPANY_ID")
    s.add_argument("--reject", metavar="RAW")
    s.set_defaults(fn=cmd_review)

    s = sub.add_parser("unmapped", help="tiers and profiles still needing curation")
    s.add_argument("--limit", type=int, default=25)
    s.set_defaults(fn=cmd_unmapped)

    s = sub.add_parser("classify", help="manually set the role for a profile string")
    s.add_argument("--set", required=True, metavar='"PROFILE=ROLE"')
    s.set_defaults(fn=cmd_classify)

    s = sub.add_parser("deptmap", help="load / validate your spo_dept_id -> branch mapping")
    s.add_argument("--map", default="dept_map.csv")
    s.add_argument("--check", action="store_true",
                   help="validate and show coverage without changing anything else")
    s.set_defaults(fn=cmd_deptmap)

    s = sub.add_parser("report", help="summary of the built graph")
    s.set_defaults(fn=cmd_report)

    s = sub.add_parser("export", help="dump the graph as JSON for the app")
    s.add_argument("--out", default="kg_export.json")
    s.add_argument("--mode", choices=["signals", "raw"], default="signals",
                   help="signals (default): normalized 0-1 features, no counts. "
                        "raw: includes counts, internal use only.")
    s.set_defaults(fn=cmd_export)

    args = p.parse_args()
    sys.exit(args.fn(args) or 0)


if __name__ == "__main__":
    main()
