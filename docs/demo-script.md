# NOVA — proof-first reasoning companion — 3-minute demo video script

**Version basis:** v1.6 submission system (API 0.4.0), script written
2026-11-03 for the Nov 4 submission. This script replaces the
Oct 26–27 script in full — the old `/concept` endpoint and the
+0.460 / +0.472 / 132–135-of-250 numbers are superseded and must not
be used.

**Format:** 180 seconds. Screen capture + narration throughout; no
on-camera appearance required (works as voiceover-only). Every number
spoken is a verified measurement — sources at the end.

**FILMING NOTE — read first:** film the system beat against the
**local run** of the API. The cloud service's `GET /health` is
verified live (HTTP 200, API 0.4.0) at
https://nova-proof-api-118169638073.us-central1.run.app, but
`POST /reason` has **not** yet been verified from an outside network
(sandbox POSTs never reached Cloud Run). The cloud call may be filmed
instead **only if** this check, run from a phone or desktop first,
returns `"answer": 125`:

```sh
curl -X POST https://nova-proof-api-118169638073.us-central1.run.app/reason \
  -H 'Content-Type: application/json' \
  -d '{"question": "Ciro refunded Aldo $25. Aldo received $160 from Berta. Aldo gave Ciro $60. How much money does Aldo have left from the $160?"}'
```

---

## 0:00–0:30 — THE PROBLEM (30s)

**On screen:** a plain chat window with Muse Spark. The presenter
pastes the trap story:

> "Nora said she would give Ben $40, but she never gave it. Nora gave
> Ben $15. How much money does Ben have left from what Nora gave him?"

**Narration:**
> "A money story a child can follow — with one catch. The first
> transfer never happened. It's negated, right there in the text."

**On screen:** Spark's live answer appears (film the real take).

**Narration:**
> "Asked on its own, the model skims past the negation and answers
> with total confidence — and it's wrong. On a reserved set of 250
> trap stories like this one, Muse Spark alone scores 0.540. Barely
> better than a coin flip, delivered in perfect grammar."

**On-screen text (counter):** `Spark alone on trap stories: 0.540`

**Production note:** if the live take happens to answer correctly,
cut to a recorded failure from the reserved run instead — the 0.540
figure is the measured claim, not this single take.

---

## 0:30–1:30 — THE SYSTEM (60s)

### Scene A — the same story, through NOVA (0:30–1:05)

**On screen:** a terminal. The presenter posts the same story to the
local API:

```json
POST /reason
{"question": "Nora said she would give Ben $40, but she never gave it. Nora gave Ben $15. How much money does Ben have left from what Nora gave him?"}
```

**On screen, in sequence:** the parsed events appear (the $40 transfer
marked negated — it never happened; the $15 transfer recorded), then
the ledger lines, then the proof trace, ending in the answer: **15**.

**Narration:**
> "Same story, through NOVA. The concept engine parses it into
> events — who gave what to whom — and the negated transfer is
> marked as never having happened. The ledger does the arithmetic
> deterministically and produces a proof. Every step inspectable.
> Not a vibe — a proof."

**On screen:** the companion prompt that goes to Spark, in two
labelled parts: `THE QUESTION, EXACTLY AS ASKED` (the story, word for
word) and `WHAT NOVA VERIFIED` (the answer, the proof trace, the
negation flagged).

**Narration:**
> "Then NOVA works as the model's companion. Spark receives the
> original question word for word — never a rewrite — plus what NOVA
> verified: exact arithmetic, a proof trace, word meanings in
> context. Information the model could not supply itself."

**On screen:** Spark's final answer: **$15**, following the proof.

**Narration:**
> "Spark writes the final answer — and it follows the proof."

### Scene B — the honest unknown (1:05–1:30)

**On screen:** a second story is posted:

> "John gave Tom $20. He gave Sarah $10. How much money does Tom
> have?"

**Narration:**
> "Now a story that genuinely cannot be answered. Who is 'he'? The
> two readings give different answers."

**On screen:** NOVA's response — no verified answer. It abstains and
names the reason: the actor of the second transfer is ambiguous.

**Narration:**
> "NOVA abstains, and says why. So the model's final answer doesn't
> invent a number — it says the question can't be determined as
> written. An honest 'I don't know' is part of the product."

---

## 1:30–2:30 — THE EVIDENCE (60s)

**On screen:** number cards, one at a time. Narration per card:

**Card 1:** `0.540 → 0.880` (fuller pipeline: `0.988`)
> "On the reserved trap set, the same unchanged model goes from
> 0.540 alone to 0.880 with the companion attached. The fuller
> pipeline reaches 0.988."

**Card 2:** `Live head-to-head: 39/40 vs 36/40`
> "In the latest live confirmation run, the current companion beat
> the previous version, 39 out of 40 to 36 — with no category
> regressions."

**Card 3:** `Refunds 5/5 · Negations 5/5`
> "On the trap classes that fool the model — refunds and negations —
> NOVA verified five of five each in that live run, and the model
> followed the proofs."

**Card 4:** `250/250 deterministic · 391 unit tests`
> "Deterministically, the system is exact: 250 out of 250 on both the
> frozen and the fresh sets, and 391 unit tests passing."

**Card 5:** `Refund-first stories: 0/19 → 19/19`
> "The final upgrade, finished yesterday: stories that state the
> refund before the transfer it refunds went from zero of nineteen
> to nineteen of nineteen — and by construction, not one answer the
> system had already certified changed."

---

## 2:30–3:00 — THE ASK (30s)

**On screen:** the live service URL, large:
`https://nova-proof-api-118169638073.us-central1.run.app`

**Narration:**
> "NOVA is not a bigger model. It's a companion layer any small model
> can wear — exact arithmetic with a proof, word meanings in
> context, and honest unknowns — added alongside the model, with no
> retraining and no weight changes. More like the language-model
> companion that helps the language model — more information than
> what the language model could supply itself."

**Narration:**
> "It's live now on Google Cloud Run, and the full system — engine,
> evaluation harness, and every measurement behind these numbers —
> is in the public repo."

**On-screen text (final card):**
> **NOVA — the proof-first reasoning companion.**
> Live: https://nova-proof-api-118169638073.us-central1.run.app
> Startup track — Meta Global AI Developer Hackathon 2026

---

## What NOT to claim

- **No fine-tuning, no weight changes.** The model is unchanged Muse
  Spark; NOVA is an addition alongside it, never a modification of
  it. Never say "the model got smarter."
- **NOVA holds no general knowledge.** On a 60-question textbook
  science test, NOVA alone verified 0 of 60 — it abstained on all of
  them, because Spark already knows that material and NOVA stores no
  science facts. The assisted gain there was behavioral (refusing to
  guess an unanswerable question), not informational. Do not present
  NOVA as a knowledge system; its value is exact reasoning, proofs,
  and ambiguity discipline.
- **The cloud POST round-trip is not yet verified from outside.**
  `GET /health` is verified live (200, API 0.4.0). `POST /reason` is
  verified locally; from the build sandbox, POSTs never reached
  Cloud Run. Film the local run unless the curl check at the top of
  this script passes first — do not present the URL as POST-proven
  until it has.
- **Superseded numbers — never use:** +0.460 / +0.472 net, +0.404
  over retrieval, alone 132–135/250, anything about the `/concept`
  endpoint, the "+0.496" v1 headline.
- **The standalone sentence classifier is not part of this
  submission.** It is a separate, unattached component and is not
  claimed anywhere in the video or the form.

## Sources (all recorded, in-repo)

- Reserved-set arms (alone 0.540, companion 0.880, fuller pipeline
  0.988): `EVAL_RESULTS.md`, reserved main run records.
- Live confirmation, 39/40 vs 36/40, refunds 5/5, negations 5/5:
  `live_test_2026-11-03_v15/` run records and scores.
- Deterministic 250/250 (frozen + fresh), 391 unit tests:
  `tests/run_all.py` output, post-promotion verification in the main
  repo.
- Refund-first class 0/19 → 19/19, zero certified answers changed:
  `ADVANCE_V16.md`, `probes_v16/` (before/after recorded runs).
- Science test (NOVA alone verified 0/60, assisted arms 60/60,
  Spark alone 59/60): `science_test_2026-11-03/` records and
  `SCIENCE_QA.md`.
- Ambiguity probe (Scene B): `eval/data/ambiguous_probes.jsonl`.
