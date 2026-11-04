# NCA v0.5 — Code audit and external research

## Source reviewed
The local v0.4 ZIP and its Python source, tests and README. The user's later cloud NCA and its full experimental traces were not available here.

## Findings fixed
1. The three regex parsers enumerated matches by parser type, not textual order. Scoped balances therefore risked applying transactions in the wrong sequence. Events are now sorted by source position.
2. Financial values were floats. Internally use Decimal for cents.
3. Multiple matching starting transfers could be incorrectly certified. Now leave the result unsupported.
4. An explicit empty lexicon was silently replaced by the demo lexicon.
5. File-backed SQLite connections could not safely be reused from another thread; connections are now per-thread. In-memory databases are intentionally not shared across threads.

## Remaining engineering risks
- Lexical coverage is five handcrafted entries, not a dictionary.
- Ledger parser is deliberately limited, cannot safely infer total wealth, and has no general co-reference or full negation scope parser.
- `VERIFIED` is verified only within the limited parser assumptions, not externally verified truth.
- Some independent symbolic proof functions reason over supplied facts, not real-world factual accuracy.
- No authenticated production API, remote service deployment, or live LLM end-to-end test.
- Thread-local SQLite connections need lifecycle cleanup under production workloads.
- A rigorous paired evaluation must compare model-only, dictionary-only, concept-only, reasoning-only and full handoff, with separate answer-leak flags and human-reviewed ground truth.

## External references
- Princeton WordNet: https://wordnet.princeton.edu/ — senses organized as distinct synsets with semantic relationships.
- WordNet license: https://wordnet.princeton.edu/license-and-commercial-use — attribution and license requirements, including commercial use.
- Python sqlite3: https://docs.python.org/3/library/sqlite3.html — `check_same_thread` and connection/thread behavior.

## Validation
Run `python -m unittest discover -s tests -q` from project root.
