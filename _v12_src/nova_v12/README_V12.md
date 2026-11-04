# NOVA Cognitive Adapter v1.2 — Semantic Graph and External Lexicon

Local research prototype, not the unavailable production cloud NCA.

## Changes
- Load externally supplied sense dictionaries using `CognitiveSystem(lexicon_path='words.json')`.
- Validate dictionary entry shapes; avoid silently fabricating senses.
- Build a separate sense graph with `has_sense`, `synonym`, and `antonym` relations.
- Preserve distinct senses and context cues in the LLM handoff.
- Keep original question, proof status, parser coverage, and unparsed actions inspectable.
- Prevent `UNSUPPORTED` from being interpreted as a universal verdict that a question is unanswerable.
- Existing independent ledger and lexical pathways preserved.

## Known limitations
- Default dictionary is five hand-curated terms; **no full WordNet ingestion**.
- Concept graphs reflect candidate lexical relationships, not validated contextual understanding.
- Ledger parser remains restricted to narrow transaction patterns; unparsed clauses may exist.
- No actual LLM, phone APK, PC installer, or live cloud integration is included.
- These unit tests are not evidence of general language-model uplift.

## Run
`python -W error::ResourceWarning -m unittest discover -s tests -q`

## Test a custom lexicon
Create `words.json` as an object mapping words to lists of senses, each containing a `meaning` and optional `synonyms`, `antonyms`, and `cues` arrays.
