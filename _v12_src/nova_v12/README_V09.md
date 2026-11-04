# NOVA v0.9 — SQLite connection lifecycle repair

This is a focused maintenance release of the v0.8 **local prototype**, not a claim to have fixed the unavailable cloud NCA implementation.

## Fixed
- Replaced unmanaged thread-local raw SQLite connections with per-thread connection owners that close their database handles on thread teardown.
- Added explicit `Knowledge.close()` and context-manager support (`with Knowledge(path) as db:`).
- Access after closing raises `RuntimeError` rather than silently reconnecting.
- Added lifecycle and multi-thread regression tests; run tests with ResourceWarnings promoted to errors.

## Known limitations
- `:memory:` databases remain private to each thread. Use a file-backed SQLite database when sharing knowledge across workers.
- `close()` must be called after all workers finish. A close invoked while workers are still active is not a synchronization barrier; production systems should manage worker shutdown explicitly.
- The parser remains narrow and can still misread unfamiliar transaction language. A VERIFIED label means supported by this parser's assumptions, not externally proven truth.
- No real model inference or new benchmark was performed in this maintenance update.

## Run
`python -W error::ResourceWarning -m unittest discover -s tests -q`
