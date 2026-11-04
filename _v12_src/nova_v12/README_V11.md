# NOVA Cognitive Adapter v1.1 — Conservative reasoning

Changes: limited explicit negation parsing; unparsed financial action detection even without dollar signs; self-transfer cannot establish a starting deposit; refunds not counted as spending; original question and raw traces preserved; model remains free to reason when NOVA is unsupported.

Limitations: narrow templates only; demo lexicon; no live LLM inference; no production cloud source or G1/reserved raw evaluations available. VERIFIED is internal to the limited parser, not externally established truth.

Run: `python -W error::ResourceWarning -m unittest discover -s tests -q`
