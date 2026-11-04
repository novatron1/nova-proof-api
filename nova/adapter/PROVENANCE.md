# Provenance — `nova/adapter/`

These modules are vendored **verbatim** (md5-verified identical) from the
user's uploaded artifact:

- Source: `~/workspace/nova-cognitive-adapter-v03/nova_cognitive_adapter/nova/`
  (NOVA Cognitive Adapter v0.3, built by the user, Oct 26 2026)
- Vendored: `core.py`, `language.py`, `concepts.py`, `meta.py`, `__init__.py`
- Baseline at vendoring time: the source's own test suite passes 20/20.

Do **not** edit these files in place. If the adapter changes, re-vendor from
the user's new upload and update the md5 record below.

## Why vendored, not imported

The adapter is the user's artifact and lives outside this repo. The
hackathon repo must be self-contained (it becomes the public GitHub repo),
so the modules it depends on are copied here. The new semantic layer in
`nova/semantic/` is the integration code and is written for this repo.

## md5 at vendoring time (Oct 26 2026)

- core.py:     63f279f88930040a795d2aa692ad1650
- language.py: 9d455c3a29964645b2b487e4ddaf4410
- concepts.py: 890fd72366e19a6334abd41dd378fc9e
- meta.py:     bec746d0dc177bd0140f774f8bdb7798
- __init__.py: c9ff451f0616d18e4a5e6ff699bb0984

## What is NOT vendored

- `server.py` from the adapter: superseded by this repo's `nova/api.py`,
  which now exposes the same capabilities plus the shared-frame `/concept`
  endpoint. The adapter's loopback dev server is not needed here.
- `demo.py`, `tests/`, `README.md`: the adapter's own; its tests are
  re-run against the vendored copy by `tests/test_adapter_vendored.py`.

## Known limits of the vendored code (from the adapter's own README)

- `meta.py` is an OpenAI-compatible chat-completions client. It has NOT
  been validated against Meta's native Model API — do not assume
  compatibility. No model calls are made by any deterministic path.
- `language.py` is a deliberately narrow heuristic extractor, not a
  general parser. It may misidentify roles and word senses.
- The knowledge store ships empty; licensed dictionary/encyclopedia data
  must be imported by the user.
