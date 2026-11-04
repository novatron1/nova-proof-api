# NOVA v0.8 — conservative coverage and raw inspection

Incremental rebuild of v0.7. Local prototype, not the cloud system.

Changes: uncovered monetary amounts in the story and complex conditional/negation expressions prevent a VERIFIED result; records include unparsed spans. This protects against falsely certified partial parsing. Existing model handoff retains original question and permits independent model reasoning when NOVA lacks proof.

Limits: cannot interpret refunds, lending, arbitrary monetary expressions, or all forms of English; no real LLM run or new external benchmark. Do not infer that passing unit tests proves semantic generalization. Raw JSON traces are illustrative local engine outputs only.

Run: `python -m unittest discover -s tests -q`.
