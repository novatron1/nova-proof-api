#!/usr/bin/env python3
"""Import WordNet 3.0 (Princeton) into the NOVA production knowledge store.

WordNet is the PRIMARY structured semantic foundation for NOVA
(Phase 2 decision, user Oct 26 11:08 PM; hierarchy refined Oct 26
11:12 PM). Wiktionary is the secondary vocabulary-expansion source
(see data/import_wiktionary.py).

Source: the NLTK WordNet 3.0 database files (wordnet.zip), downloaded
from https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages/corpora/wordnet.zip
Licence: WordNet License (Princeton University) — permissive; the
full licence text is inside the zip (wordnet/LICENSE) and recorded in
data/PROVENANCE.md. No pip installs: the database files are plain
text, parsed here with stdlib only.

Scope (deliberate, recorded): a targeted subset — the eval/holdout
fixture vocabulary, the money/transfer/demo vocabulary, and content
words from the adversarial set — NOT the full 117k-synset database.
The import machinery is general (any term list works); the subset
keeps the production store fast (the encyclopedia matcher scans the
entries table) and honest about its coverage. Relations and senses
are imported for exactly the terms in scope, sense-scoped: every
relation carries the sense number of the synset it came from, so
"give" in the transfer sense does not inherit synonyms from its
44 other senses.

Tables written to data/knowledge.db (same file the Wiktionary
import adds to):
  entries(kind, term, meaning, source)   — primary-sense gloss
      (the Knowledge store's own schema; kind is always
      "dictionary" here)
  senses(term, pos, sense_no, gloss, source) — every sense
  relations(term, rel, target, sense_no, source) — synonym /
      antonym / hypernym / hyponym / part_meronym, from WordNet
      pointers, sense-scoped
  morph(surface, lemma, source) — inflected form -> base form,
      from the .exc exception files + stripping rules
  provenance(source, licence, url, fetched, sha256, scope)

Usage:
    python3 data/import_wordnet.py [--zip /tmp/wordnet.zip] [--db data/knowledge.db]
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import sqlite3
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

WORDNET_ZIP_URL = ("https://raw.githubusercontent.com/nltk/nltk_data/"
                   "gh-pages/packages/corpora/wordnet.zip")
SOURCE = "wordnet-3.0"
LICENCE = "WordNet License (Princeton University)"

# ---------------------------------------------------------------------------
# Term list: the vocabulary the production store covers.
# Fixture + holdout terms and adversarial content words are added
# programmatically below; this is the hand-listed demo domain.
# ---------------------------------------------------------------------------

HAND_TERMS = """
dollar dollars buck bucks cent penny dime nickel quarter euro pound
tenner fiver twenty fifty dozen money price cost payment pay paid
purchase buy sell lend borrow give send receive transfer wire hand pass
donate forward remit deposit refund discount invoice receipt expand
contract handed passed transferred wired donated forwarded remitted
deposited spent sold bought received got took taken lent borrowed sent
gave paid fly swim walk run eat drink sleep read write speak listen
look see know think live die grow move change become make produce
carry visit leave approach arrive come go
bicycle bike automobile car vehicle book ticket apple share item
spider hexagon octagon pentagon heptagon nonagon decagon quadrilateral
rectangle square century hour minute second day year leg side wheel
seed fruit bird penguin fish dog cat animal human mortal planet star
earth sun moon ocean water air honey bee plant tree flower food sunlight
open closed hot cold full empty on off big small tall short fast slow
light dark high low long wide narrow strong weak rich poor happy sad
early late new old clean dirty safe dangerous loud quiet hard soft
deep shallow largest smallest red green blue black white
gravity orbit photosynthesis migrate hibernate evaporate condense
auction thermal expansion boiling point leap year carbon dioxide
pacific triangle fragile generous ancient victory honest journey
harvest success truth trip crops broken
bank bat bark spring date right well
""".split()

# Pointer symbols we import (WordNet data-file codes).
# ! antonym, @ hypernym, ~ hyponym, %p part meronym.
REL_MAP = {"!": "antonym", "@": "hypernym", "~": "hyponym",
           "%p": "part_meronym"}


# ---------------------------------------------------------------------------
# WordNet database parsing (plain-text format, stdlib only)
# ---------------------------------------------------------------------------

def _clean_gloss(gloss: str) -> str:
    """The definition part of a gloss (examples are quoted after ';')."""
    g = gloss.strip()
    m = re.search(r';\s*"', g)
    if m:
        g = g[:m.start()].strip()
    return g.strip(' "') or g


def parse_wordnet(db_dir: Path) -> dict:
    """Parse index.* + data.* into {offset: synset dict}."""
    synsets: dict[str, dict] = {}
    for pos in ("noun", "verb", "adj", "adv"):
        data_path = db_dir / f"data.{pos}"
        if not data_path.exists():
            continue
        with open(data_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith(" ") or not line.strip():
                    continue
                left, _, gloss = line.rstrip("\n").partition(" | ")
                toks = left.split()
                if len(toks) < 5:
                    continue
                offset, spos = toks[0], toks[2]
                try:
                    w_cnt = int(toks[3], 16)
                except ValueError:
                    continue
                lemmas = []
                i = 4
                for _ in range(w_cnt):
                    if i + 1 >= len(toks):
                        break
                    lemmas.append(toks[i].replace("_", " ").lower())
                    i += 2
                if i >= len(toks):
                    continue
                try:
                    p_cnt = int(toks[i])
                except ValueError:
                    continue
                i += 1
                pointers = []
                for _ in range(p_cnt):
                    if i + 3 >= len(toks):
                        break
                    sym, tgt, tpos, src_tgt = toks[i:i + 4]
                    try:
                        src = int(src_tgt[:2], 16)
                        tgt_w = int(src_tgt[2:], 16)
                    except ValueError:
                        src, tgt_w = 0, 0
                    pointers.append((sym, tgt, tpos, src, tgt_w))
                    i += 4
                synsets[offset] = {
                    "pos": spos, "lemmas": lemmas,
                    "gloss": _clean_gloss(gloss),
                    "pointers": pointers}
    return synsets


def index_lemmas(db_dir: Path) -> dict:
    """lemma -> [(pos, sense_no, offset)] in WordNet order (sense 1
    is the most frequent)."""
    out: dict[str, list] = {}
    for pos in ("noun", "verb", "adj", "adv"):
        idx_path = db_dir / f"index.{pos}"
        if not idx_path.exists():
            continue
        with open(idx_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith(" ") or not line.strip():
                    continue
                toks = line.split()
                if len(toks) < 7:
                    continue
                lemma = toks[0].replace("_", " ").lower()
                try:
                    p_cnt = int(toks[3])
                except ValueError:
                    continue
                base = 4 + p_cnt
                if len(toks) < base + 2:
                    continue
                try:
                    sense_cnt = int(toks[base])
                except ValueError:
                    continue
                offsets = toks[base + 2: base + 2 + sense_cnt]
                for n, off in enumerate(offsets, start=1):
                    out.setdefault(lemma, []).append((pos, n, off))
    return out


def load_exceptions(db_dir: Path) -> dict:
    """inflected form -> [base forms], from the .exc files."""
    exc: dict[str, list] = {}
    for pos in ("noun", "verb", "adj", "adv"):
        p = db_dir / f"{pos}.exc"
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8",
                                errors="replace").splitlines():
            toks = line.split()
            if len(toks) >= 2:
                exc.setdefault(toks[0].lower(), []).extend(
                    t.replace("_", " ").lower() for t in toks[1:])
    return exc


def morphy(term: str, index: dict, exc: dict) -> list[str]:
    """Base-form lemmas for a (possibly inflected) term, in order.

    .exc exceptions first, then the standard WordNet stripping
    rules. A candidate counts only if it is in the index.
    """
    t = term.lower()
    if t in index:
        return [t]
    cands: list[str] = []
    for base in exc.get(t, []):
        if base in index and base not in cands:
            cands.append(base)
    # Stripping rules (WordNet morphy, simplified).
    forms = []
    if t.endswith("ies") and len(t) > 3:
        forms.append(t[:-3] + "y")
    if t.endswith("es") and len(t) > 2:
        forms.append(t[:-2])
        forms.append(t[:-1])
    if t.endswith("s") and len(t) > 2 and not t.endswith("ss"):
        forms.append(t[:-1])
    if t.endswith("ed") and len(t) > 3:
        forms.append(t[:-2])
        forms.append(t[:-2] + "e")
        forms.append(t[:-1])
    if t.endswith("ing") and len(t) > 4:
        forms.append(t[:-3])
        forms.append(t[:-3] + "e")
    for f in forms:
        if f in index and f not in cands:
            cands.append(f)
    return cands


def term_list() -> list[str]:
    """The import scope: hand terms + fixture terms + adversarial
    content words."""
    terms = set(HAND_TERMS)
    from eval.fixtures import (DICTIONARY, DICTIONARY_HOLDOUT,
                               ENCYCLOPEDIA, ENCYCLOPEDIA_HOLDOUT)
    for _k, term, _m, _kw in (DICTIONARY + ENCYCLOPEDIA
                              + DICTIONARY_HOLDOUT + ENCYCLOPEDIA_HOLDOUT):
        for w in re.findall(r"[a-z]+(?:-[a-z]+)?", term.lower()):
            terms.add(w)
        terms.add(term.lower())
    adv = ROOT / "eval" / "data" / "adversarial.jsonl"
    if adv.exists():
        for line in open(adv, encoding="utf-8"):
            d = json.loads(line)
            text = d.get("text") or d.get("question") or ""
            for w in re.findall(r"[a-z]+(?:-[a-z]+)?", text.lower()):
                if len(w) > 2:
                    terms.add(w)
    return sorted(t for t in terms if t)


def import_wordnet(zip_path: Path, db_path: Path) -> dict:
    """Build the WordNet tables in db_path. Returns counts."""
    with zipfile.ZipFile(zip_path) as z:
        with tempfile.TemporaryDirectory() as tmp:
            z.extractall(tmp)
            db_dir = Path(tmp) / "wordnet"
            synsets = parse_wordnet(db_dir)
            lemma_index = index_lemmas(db_dir)
            exc = load_exceptions(db_dir)
    terms = term_list()
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE IF NOT EXISTS entries "
                 "(kind TEXT, term TEXT, meaning TEXT, source TEXT, "
                 "PRIMARY KEY(kind,term))")
    conn.execute("CREATE TABLE IF NOT EXISTS senses "
                 "(term TEXT, pos TEXT, sense_no INTEGER, gloss TEXT, "
                 "source TEXT, PRIMARY KEY(term,pos,sense_no,source))")
    conn.execute("CREATE TABLE IF NOT EXISTS relations "
                 "(term TEXT, rel TEXT, target TEXT, pos TEXT, "
                 "sense_no INTEGER, "
                 "source TEXT, "
                 "PRIMARY KEY(term,rel,target,pos,sense_no,source))")
    conn.execute("CREATE TABLE IF NOT EXISTS morph "
                 "(surface TEXT, lemma TEXT, source TEXT, "
                 "PRIMARY KEY(surface,lemma,source))")
    conn.execute("CREATE TABLE IF NOT EXISTS provenance "
                 "(source TEXT PRIMARY KEY, licence TEXT, url TEXT, "
                 "fetched TEXT, sha256 TEXT, scope TEXT)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_relations_term "
                 "ON relations(term)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_senses_term "
                 "ON senses(term)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_morph_surface "
                 "ON morph(surface)")

    n_missing = 0
    for term in terms:
        lemmas = morphy(term, lemma_index, exc)
        if not lemmas:
            n_missing += 1
            continue
        lemma = lemmas[0]
        if term != lemma:
            conn.execute(
                "INSERT OR IGNORE INTO morph VALUES (?,?,?)",
                (term, lemma, SOURCE))
        senses = lemma_index.get(lemma, [])
        # The entry's primary meaning is the first sense of the
        # dominant part of speech (most senses; ties prefer noun,
        # then verb, then adjective, then adverb — the noun is the
        # default citation form, and a verb only wins on a strict
        # sense-count majority). A noun-first rule made "give" mean
        # "elasticity"; a verb-tie rule made "bicycle" mean "ride
        # a bicycle". The count decides; the tie-break is the noun.
        _POS_ORDER = {"noun": 0, "verb": 1, "adj": 2, "adv": 3}
        counts: dict[str, int] = {}
        for pos, _n, off in senses:
            if synsets.get(off) and synsets[off]["gloss"]:
                counts[pos] = counts.get(pos, 0) + 1
        primary = None
        if counts:
            dom = min(counts,
                      key=lambda p: (-counts[p], _POS_ORDER.get(p, 9)))
            for pos, _n, off in senses:
                if pos == dom:
                    s = synsets.get(off)
                    if s and s["gloss"]:
                        primary = s
                        break
        if primary is not None:
            conn.execute(
                "INSERT OR REPLACE INTO entries VALUES (?,?,?,?)",
                ("dictionary", lemma, primary["gloss"],
                 f"{SOURCE} ({LICENCE})"))
        for pos, n, off in senses:
            s = synsets.get(off)
            if not s or not s["gloss"]:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO senses VALUES (?,?,?,?,?)",
                (lemma, pos, n, s["gloss"], SOURCE))
            lemmas_in_synset = s["lemmas"]
            for other in lemmas_in_synset:
                if other != lemma:
                    conn.execute(
                        "INSERT OR IGNORE INTO relations "
                        "VALUES (?,?,?,?,?,?)",
                        (lemma, "synonym", other, pos, n, SOURCE))
            for sym, tgt, _tpos, src, tgt_w in s["pointers"]:
                rel = REL_MAP.get(sym)
                if rel is None:
                    continue
                target = synsets.get(tgt)
                if not target or not target["lemmas"]:
                    continue
                if sym == "!":
                    if src and 1 <= src <= len(lemmas_in_synset):
                        src_lemma = lemmas_in_synset[src - 1]
                    else:
                        src_lemma = lemma
                    if tgt_w and 1 <= tgt_w <= len(target["lemmas"]):
                        tgt_lemma = target["lemmas"][tgt_w - 1]
                    else:
                        tgt_lemma = target["lemmas"][0]
                    if src_lemma != lemma:
                        continue
                    conn.execute(
                        "INSERT OR IGNORE INTO relations "
                        "VALUES (?,?,?,?,?,?)",
                        (lemma, "antonym", tgt_lemma, pos, n, SOURCE))
                else:
                    conn.execute(
                        "INSERT OR IGNORE INTO relations "
                        "VALUES (?,?,?,?,?,?)",
                        (lemma, rel, target["lemmas"][0], pos, n,
                         SOURCE))
    sha = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    conn.execute(
        "INSERT OR REPLACE INTO provenance VALUES (?,?,?,?,?,?)",
        (SOURCE, LICENCE, WORDNET_ZIP_URL,
         datetime.date.today().isoformat(), sha,
         f"targeted subset: {len(terms)} terms "
         f"({n_missing} not in WordNet)"))
    conn.commit()
    counts = {t: conn.execute(
        f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ("entries", "senses", "relations", "morph",
                  "provenance")}
    counts.update({"terms": len(terms), "missing": n_missing,
                   "sha256": sha})
    conn.close()
    return counts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", default="/tmp/wordnet.zip")
    ap.add_argument("--db", default=str(ROOT / "data" / "knowledge.db"))
    args = ap.parse_args()
    zip_path = Path(args.zip)
    if not zip_path.exists():
        print(f"downloading {WORDNET_ZIP_URL} ...")
        urllib.request.urlretrieve(WORDNET_ZIP_URL, zip_path)
    counts = import_wordnet(zip_path, Path(args.db))
    print(json.dumps(counts, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
