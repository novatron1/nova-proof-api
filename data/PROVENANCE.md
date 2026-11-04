# Data provenance — NOVA production knowledge store

The production store (`data/knowledge.db`, seeded by `data/seed.py`
from the importers below) contains **only openly licensed data**.
Every entry, sense, and relation carries its source; the
`provenance` table records the licence, URL, fetch date, checksum,
and scope for each source.

Store contents at seed time (2026-10-27):

| table | rows |
|---|---|
| entries | 285 |
| senses | 3,418 |
| relations (sense- and POS-scoped) | 12,904 |
| morph mappings | 27 |
| provenance rows | 2 |

Database file: 2,134,016 bytes.

## WordNet 3.0 — PRIMARY structured semantic foundation

- **Source:** Princeton WordNet 3.0, DB files (`index.*`, `data.*`)
  from the NLTK data distribution.
- **Download URL:**
  `https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages/corpora/wordnet.zip`
  (10,775,600 bytes)
- **SHA-256:**
  `cbda5ea6eef7f36a97a43d4a75f85e07fccbb4f23657d27b4ccbc93e2646ab59`
- **Licence:** WordNet License (Princeton University).
  Permits use, copying, modification, and distribution, with the
  copyright notice and licence text retained.
- **Importer:** `data/import_wordnet.py` — stdlib-only parser of the
  DB files (no `nltk`, no pip). Parses synsets, hypernyms, hyponyms,
  meronyms, holonyms, antonyms, similar-to, and pertainyms; builds
  morph mappings from the exception lists.
- **Scope:** a targeted subset of 316 terms (the eval vocabulary,
  common concepts, and the Phase 2 probe vocabulary — see
  `HAND_TERMS` in the importer). 20 of the 316 are **not in
  WordNet** — mostly names, function words, and the nonce word
  "flibberty". "Thermal expansion" is genuinely absent from
  WordNet (verified: 0 hits in `index.noun` — not a morphy bug).
- **Contribution to the store:** 275 entries, 2,501 senses,
  12,781 relations, 27 morph mappings.
- **Entry rule:** an entry's primary meaning is the first sense of
  its dominant POS (the POS with the most senses; ties break to
  noun, then verb, adjective, adverb). This rule was iterated in
  the build: noun-first made "give" mean "elasticity"; verb-tie
  made "bicycle" mean "ride a bicycle". Quirk to know: "light"'s
  primary is the adjective ("of comparatively little physical
  weight") because it has the most senses.

## Wiktionary — SECONDARY vocabulary-expansion source

- **Source:** the English Wiktionary, via its public APIs.
- **API endpoints:**
  - Definitions:
    `https://en.wiktionary.org/api/rest_v1/page/definition/<term>`
  - Synonym/antonym sections (parse API):
    `https://en.wiktionary.org/w/api.php?action=parse&prop=wikitext`
- **Licence:** CC BY-SA 4.0. All Wiktionary content used here is
  attributed in the `source` field of every entry/sense/relation
  (`wiktionary (CC BY-SA 4.0)`), and the licence is recorded in
  the `provenance` table.
- **Importer:** `data/import_wiktionary.py` — REST definition API
  plus the parse API for synonym/antonym sections. User-Agent
  `NOVA-Cognitive-Adapter/0.3`; 0.1 s sleep between calls.
- **Scope:** a targeted subset of 76 terms (`data/wiktionary_terms.txt`
  — the terms WordNet covers thinly plus the Phase 2 probe
  vocabulary). **Fill-gaps-only for entries:** where WordNet
  already has an entry, Wiktionary contributes senses and
  relations but does not replace the entry; relations are a union
  of both sources. Wiktionary contributed only 10 new entries.
- **Gaps (no definition found):** "boiling point of water",
  "thermal expansion", "pacific ocean" (the lowercase title
  fails; "Pacific Ocean" is covered by WordNet). "Boiling point"
  and "Pacific Ocean" are covered (Wiktionary and WordNet
  respectively).
- **Contribution to the store:** 10 entries, 917 senses,
  123 relations.

## What is deliberately NOT in the store

The 30 hand-authored eval-fixture entries (the harness's stand-in
knowledge for the frozen eval set) are **not merged** into the
production store. Merging them would conflate eval knowledge with
production knowledge: the frozen eval would then measure a store
that was built from the eval's own answers. The production store
is licensed data only, and the frozen-eval-through-production run
(222/250) is the honest measure of that store against the frozen
set — the dictionary/encyclopedia shortfall is the fixture-keyword
gap, not a store failure (see `EVAL_RESULTS.md` §12).

**Recommendation for the parent:** merge the 30 fixture entries
as a documented "core facts" source (a third, explicitly labelled
source with its own provenance row), so the production store
covers the fixture vocabulary. That is a follow-up decision, not
something done silently inside Phase 2.

## Reproducing the store

```bash
cd nova-proof-api
python3 data/import_wordnet.py    # downloads the WordNet zip,
                                  # parses it, writes to knowledge.db
python3 data/import_wiktionary.py # fetches the 76 terms via the API
python3 data/seed.py              # (re-)seeds the production store
```

The WordNet zip is cached at `/tmp/wordnet.zip` after the first
download; the importer re-uses it when present.
