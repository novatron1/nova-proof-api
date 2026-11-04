#!/usr/bin/env python3
"""Import Wiktionary (English) into the NOVA production knowledge store.

Wiktionary is the SECONDARY vocabulary-expansion source for NOVA
(Phase 2 decision, user Oct 26 11:08 PM; hierarchy refined Oct 26
11:12 PM). WordNet (data/import_wordnet.py) is the primary
structured foundation and is imported FIRST; this script only fills
gaps WordNet leaves (slang and money words like "tenner"/"bucks",
multi-word terms, usage senses) and unions synonym/antonym
relations from both sources.

Source: the Wiktionary REST definition API + the MediaWiki parse API,
  https://en.wiktionary.org/api/rest_v1/page/definition/{term}
  https://en.wiktionary.org/w/api.php?action=parse&prop=wikitext
Licence: CC BY-SA 4.0 — every Wiktionary row carries the source tag
"wiktionary (CC BY-SA 4.0)" and the licence is recorded in
data/PROVENANCE.md. Definitions are fetched, not scraped from a
dump; the targeted term list (~200 terms) is in
data/wiktionary_terms.txt.

Rules:
  entries: INSERT ONLY IF ABSENT (WordNet wins on conflicts).
  senses: union, Wiktionary senses numbered from 101 per POS so they
      never collide with WordNet sense numbers.
  relations: union (synonym/antonym), source-tagged per row.

Usage:
    python3 data/import_wiktionary.py [--db data/knowledge.db]
"""
from __future__ import annotations

import argparse
import datetime
import html
import json
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = "wiktionary"
LICENCE = "CC BY-SA 4.0"
SOURCE_TAG = f"{SOURCE} ({LICENCE})"
UA = {"User-Agent": "NOVA-Cognitive-Adapter/0.3 (hackathon research; "
                    "contact novatron513@gmail.com)"}
DEF_URL = "https://en.wiktionary.org/api/rest_v1/page/definition/{}"
PARSE_URL = ("https://en.wiktionary.org/w/api.php?action=parse"
             "&prop=wikitext&format=json&page={}")


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def fetch_json(url: str):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_definitions(term: str) -> list[tuple[str, str]]:
    """(pos, definition) pairs for an English term, or []."""
    try:
        data = fetch_json(DEF_URL.format(urllib.parse.quote(term)))
    except (urllib.error.HTTPError, urllib.error.URLError, ValueError):
        return []
    out = []
    for entry in data.get("en", []):
        pos = entry.get("partOfSpeech", "").lower()
        for d in entry.get("definitions", []):
            text = _strip_html(d.get("definition", ""))
            if text:
                out.append((pos, text))
    return out


def fetch_syn_ant(term: str) -> dict:
    """{'synonym': [...], 'antonym': [...]} from the wikitext
    Synonyms/Antonyms sections (English), best-effort."""
    try:
        data = fetch_json(PARSE_URL.format(urllib.parse.quote(term)))
    except (urllib.error.HTTPError, urllib.error.URLError, ValueError):
        return {"synonym": [], "antonym": []}
    try:
        wikitext = data["parse"]["wikitext"]["*"]
    except KeyError:
        return {"synonym": [], "antonym": []}
    found: dict[str, list] = {"synonym": [], "antonym": []}
    in_english = False
    current = None
    for line in wikitext.splitlines():
        if line.startswith("==") and not line.startswith("==="):
            in_english = ("English" in line)
            current = None
            continue
        if not in_english:
            continue
        m = re.match(r"^(=+)\s*(Synonyms|Antonyms)\s*=+", line)
        if m:
            current = ("synonym" if m.group(2) == "Synonyms"
                       else "antonym")
            continue
        if line.startswith("="):
            current = None
            continue
        if current and line.startswith("*"):
            # Bullet: "* [[word]]" or "* [[word|display]]" or "* word".
            for link in re.findall(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]",
                                   line):
                w = link.strip().lower()
                if w and w not in found[current]:
                    found[current].append(w)
            if not re.search(r"\[\[", line):
                plain = line.lstrip("* ").strip().lower()
                plain = re.sub(r"\(.*?\)", "", plain).strip(" ,;")
                if plain and plain not in found[current]:
                    found[current].append(plain)
    for k in found:
        found[k] = found[k][:10]
    return found


def term_list() -> list[str]:
    p = ROOT / "data" / "wiktionary_terms.txt"
    if p.exists():
        return [t.strip().lower() for t in p.read_text().splitlines()
                if t.strip() and not t.strip().startswith("#")]
    return []


def import_wiktionary(db_path: Path, sleep: float = 0.1) -> dict:
    terms = term_list()
    conn = sqlite3.connect(db_path)
    counts = {"terms": len(terms), "entries_added": 0,
              "senses_added": 0, "relations_added": 0,
              "no_definition": []}
    for term in terms:
        defs = fetch_definitions(term)
        time.sleep(sleep)
        if not defs:
            counts["no_definition"].append(term)
            continue
        # Entries: fill gaps only (WordNet wins).
        exists = conn.execute(
            "SELECT 1 FROM entries WHERE kind='dictionary' AND term=?",
            (term,)).fetchone()
        primary = None
        for pos, text in defs:
            if pos in ("noun", "verb", "adjective", "adverb"):
                primary = text
                break
        if primary is None:
            primary = defs[0][1]
        if not exists:
            conn.execute(
                "INSERT INTO entries VALUES (?,?,?,?)",
                ("dictionary", term, primary, SOURCE_TAG))
            counts["entries_added"] += 1
        # Senses: union, numbered from 101 per POS.
        seen_pos: dict[str, int] = {}
        for pos, text in defs:
            n = seen_pos.get(pos, 0) + 1
            seen_pos[pos] = n
            conn.execute(
                "INSERT OR IGNORE INTO senses VALUES (?,?,?,?,?)",
                (term, pos, 100 + n, text, SOURCE))
            counts["senses_added"] += 1
        # Synonyms / antonyms from the wikitext sections.
        rels = fetch_syn_ant(term)
        time.sleep(sleep)
        for rel, targets in rels.items():
            for tgt in targets:
                cur = conn.execute(
                    "INSERT OR IGNORE INTO relations "
                    "VALUES (?,?,?,?,?,?)",
                    (term, rel, tgt, "", 0, SOURCE)).rowcount
                counts["relations_added"] += cur
    conn.execute(
        "INSERT OR REPLACE INTO provenance VALUES (?,?,?,?,?,?)",
        (SOURCE, LICENCE,
         "https://en.wiktionary.org/api/rest_v1/page/definition/",
         datetime.date.today().isoformat(), "",
         f"targeted subset: {len(terms)} terms "
         f"(definitions + synonym/antonym sections)"))
    conn.commit()
    conn.close()
    return counts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "knowledge.db"))
    args = ap.parse_args()
    counts = import_wiktionary(Path(args.db))
    print(json.dumps(counts, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
