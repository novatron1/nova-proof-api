# NOVA v0.7 — Local lexical-answer and frame-safety patch

Changes: definition-question routing from the **five-entry demonstration lexicon**; context-cue selection for polysemous words; lexical answers explicitly labeled `LEXICAL` rather than `VERIFIED`; ledger event frames passed instead of unreliable generic actor slots; raw internal ledger/lexical trace included in every handoff package. Preserves unsupported-action safeguards and the optional language-model output architecture.

This is a constrained local prototype, not the cloud NOVA implementation or a trained LLM. It does not understand arbitrary natural language or validate dictionary truth. An `UNSUPPORTED` response means the parser could not certify the answer, not that the question is unanswerable. No live external model was called.

Run `python -m unittest discover -s tests -q` and inspect `NOVA-v0.7-ten-question-raw.json` supplied separately.
