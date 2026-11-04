"""Generate the money-transfer probe set (100 questions, exact answers).

Expected answers are computed by an INDEPENDENT simulation written here
(simple balance dict + FIFO inflow lots), not by importing the system under
test. The test then checks that the parser + ledger agree with it.

Probe #1 is the canonical example, hand-verified:
  Marcus gave John $20. John gave Sarah $10.
  How much money does John have left from the $20?  -> 10
"""

import json
import random

NAMES = ["Marcus", "John", "Sarah", "Alicia", "David", "Priya",
         "Tom", "Elena", "Chris", "Maya"]
AMOUNTS = [5, 10, 15, 20, 25, 30, 40, 50, 60, 75, 80, 100]


def simulate(transfers):
    """Independent expected-value simulation.

    Returns (balances, lots) where lots[person] is a list of
    [giver, amount_remaining] in FIFO order.
    """
    balances, lots = {}, {}
    for giver, recv, amt in transfers:
        balances[giver] = balances.get(giver, 0) - amt
        balances[recv] = balances.get(recv, 0) + amt
        rem = amt
        for lot in lots.get(giver, []):
            take = min(lot[1], rem)
            lot[1] -= take
            rem -= take
            if rem == 0:
                break
        lots[giver] = [l for l in lots.get(giver, []) if l[1] > 0]
        lots.setdefault(recv, []).append([giver, amt])
    return balances, lots


def fmt_transfer(giver, recv, amt, style):
    if style == 0:
        return f"{giver} gave {recv} ${amt}."
    if style == 1:
        return f"{giver} gave ${amt} to {recv}."
    return f"{recv} received ${amt} from {giver}."


def gen_probe(rng, pid, kind):
    people = rng.sample(NAMES, 4)
    a, b, c, d = people
    x = rng.choice(AMOUNTS)
    y = rng.choice([v for v in AMOUNTS if v <= x])
    if kind == "scoped2":
        transfers = [(a, b, x), (b, c, y)]
        story = " ".join(fmt_transfer(*t, rng.randrange(3)) for t in transfers)
        q = f"How much money does {b} have left from the ${x}?"
        _, lots = simulate(transfers)
        exp = sum(left for (g, left) in lots[b] if g == a)
        return {"id": pid, "type": kind, "story": story, "question": q,
                "expected": exp}
    if kind == "total2":
        transfers = [(a, b, x), (b, c, y)]
        story = " ".join(fmt_transfer(*t, rng.randrange(3)) for t in transfers)
        q = f"How much money does {b} have?"
        balances, _ = simulate(transfers)
        return {"id": pid, "type": kind, "story": story, "question": q,
                "expected": balances[b]}
    if kind == "chain3":
        z = rng.choice([v for v in AMOUNTS if v <= y])
        transfers = [(a, b, x), (b, c, y), (c, d, z)]
        story = " ".join(fmt_transfer(*t, rng.randrange(3)) for t in transfers)
        who = rng.choice([b, c])
        q = f"How much money does {who} have?"
        balances, _ = simulate(transfers)
        return {"id": pid, "type": kind, "story": story, "question": q,
                "expected": balances[who]}
    if kind == "multi_inflow":
        w = rng.choice(AMOUNTS)
        transfers = [(a, b, x), (d, b, w), (b, c, y)]
        story = " ".join(fmt_transfer(*t, rng.randrange(3)) for t in transfers)
        if rng.random() < 0.5:
            q = f"How much money does {b} have?"
            balances, _ = simulate(transfers)
            exp = balances[b]
        else:
            q = f"How much money is left from the ${x} {a} gave {b}?"
            _, lots = simulate(transfers)
            exp = sum(left for (g, left) in lots[b] if g == a)
        return {"id": pid, "type": kind, "story": story, "question": q,
                "expected": exp}
    if kind == "distractor":
        # A transfer that does not involve the queried person.
        w = rng.choice(AMOUNTS)
        transfers = [(a, b, x), (b, c, y), (d, a, w)]
        story = " ".join(fmt_transfer(*t, rng.randrange(3)) for t in transfers)
        q = f"How much money does {b} have left from the ${x}?"
        _, lots = simulate(transfers)
        exp = sum(left for (g, left) in lots[b] if g == a)
        return {"id": pid, "type": kind, "story": story, "question": q,
                "expected": exp}
    raise ValueError(kind)


def main():
    rng = random.Random(20261026)  # fixed seed: reproducible set
    probes = [{
        "id": 1, "type": "scoped2",
        "story": "Marcus gave John $20. John gave Sarah $10.",
        "question": "How much money does John have left from the $20?",
        "expected": 10,
    }]
    kinds = (["scoped2"] * 25 + ["total2"] * 20 + ["chain3"] * 20
             + ["multi_inflow"] * 20 + ["distractor"] * 14)
    rng.shuffle(kinds)
    for i, kind in enumerate(kinds, start=2):
        probes.append(gen_probe(rng, i, kind))
    with open("data/money_probes.jsonl", "w") as f:
        for p in probes:
            f.write(json.dumps(p) + "\n")
    print(f"wrote {len(probes)} probes")


if __name__ == "__main__":
    main()
