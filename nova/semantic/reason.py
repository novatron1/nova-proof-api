"""Supervisory reasoner: shared frames in, verdict + proof out.

Consumes ConceptFrames and performs inference, reusing the vendored
adapter's four-valued propositional reasoner (yes / no / both / unknown
+ trace) and the money engine's exact ledger for balance questions.

Verdict vocabulary is fixed and honest:

* ``yes`` / ``no`` — the goal follows / its negation follows from the
  frames, with a complete proof trace.
* ``both`` — the frames support the goal AND its negation (contradictory
  premises). Reported, never silently resolved.
* ``unknown`` — the frames do not settle the goal. ``missing`` says
  exactly which slots/facts were absent, so "unknown" is informative
  instead of a shrug.

``complete`` is True only when the derivation terminated with a
definitive verdict (yes/no/both) or a computed answer. A balance answer
computed from fully deterministic frames has status ``verified``; any
answer that depended on a heuristic parse has status
``candidate_interpretation``.
"""

from __future__ import annotations

import re

from ..adapter.core import Reasoner
from ..concept.events import BalanceQuery
from ..concept.ledger import run_story
from .extract import find_query, normalize_person
from .facts import ANTONYM_ADJECTIVES, find_per_unit_fact
from .frame import MONEY_ACTIONS, MONEY_UNITS, ConceptFrame
from .translate import (frame_to_balance_query, frame_to_fact,
                        frames_to_facts, goal_frame_to_fact,
                        split_story_frames)

# Money verbs whose amount the "How much money did X pay?" question
# reads back from the story's own frames.
_AMOUNT_PAID_ACTIONS = ("purchase", "pay", "give", "send")

# A fully-specified money-transfer fact: give/send/pay(giver, recipient,
# amount), amount numeric. Used by the closed-world near-miss rule.
_MONEY_FACT_RE = re.compile(
    r"^(give|send|pay)\(([^,]+),([^,]+),([\d.]+)\)$")


def _adjective_alt_goal(goal: str) -> str | None:
    """The equivalent is/state form of an adjective goal, or None.

    ``state(iron,strong)`` <-> ``is(iron,strong)``: the copula
    question form reads an adjective complement as a state, while a
    rule's consequent is an is-a. For an adjective in the antonym map
    the two ask the same thing. Anything else (actions, non-adjective
    complements) has no equivalent form.
    """
    m = re.fullmatch(r"(state|is)\(([^,]+),([^,]+)\)", goal or "")
    if not m:
        return None
    if m.group(3) not in ANTONYM_ADJECTIVES:
        return None
    other = "is" if m.group(1) == "state" else "state"
    return f"{other}({m.group(2)},{m.group(3)})"


def _is_yes_no(frame: ConceptFrame) -> bool:
    return any(r.get("rel") == "asks_whether"
               for r in frame.relationships)


def _balance_determined(frames: list[ConceptFrame],
                        person: str | None) -> bool:
    """Is the person's balance determined by the story?

    Determined iff some non-query frame mentions the person (as giver
    or recipient) in a quantified money transfer — positive or negated.
    A person the story never mentions with a specific amount has an
    unknown balance, not $0. A person mentioned only with an
    unquantified amount ("some money") is likewise undetermined.
    """
    if person is None:
        return False
    for f in frames:
        if f.kind == "query":
            continue
        if f.what not in MONEY_ACTIONS and f.what != "refund":
            continue
        if f.quantity is None or f.units not in MONEY_UNITS:
            continue
        if (normalize_person(f.who) == person
                or normalize_person(f.recipient) == person):
            return True
    return False


class SupervisoryReasoner:
    """Reason over shared frames. Model-independent, stdlib-only.

    ``knowledge`` is the optional Knowledge store the
    knowledge-to-calculation bridge consults when a per-unit fact is
    not stated in the text itself.
    """

    def __init__(self, reasoner: Reasoner | None = None,
                 knowledge=None):
        self.reasoner = reasoner or Reasoner()
        self.knowledge = knowledge

    # -- balance questions (ledger path) ----------------------------------
    def reason_balance(self, frames: list[ConceptFrame]) -> dict:
        transfers, query, unusable, used_heuristic = split_story_frames(
            frames, allow_heuristic=True)
        if query is None:
            return {
                "verdict": "unknown", "answer": None, "proof": [],
                "complete": False,
                "status": "unknown",
                "missing": ["no balance question frame found"],
                "evidence": [],
                "unusable_frames": [f.to_dict() for f in unusable],
            }
        if not _balance_determined(frames, query.person):
            # Honesty: a balance the story never determines is unknown,
            # not $0. The ledger defaults an absent person to 0, but
            # "no transfers mention Zoe" is not evidence Zoe has $0 —
            # it is evidence of nothing about Zoe.
            return {
                "verdict": "unknown", "answer": None,
                "proof": [f"No quantified transfer in the story mentions "
                          f"{query.person}, so the balance cannot be "
                          f"determined."],
                "complete": False, "status": "unknown",
                "missing": [f"balance for {query.person} is not "
                            f"determined by the story"],
                "evidence": [],
                "unusable_frames": [f.to_dict() for f in unusable],
            }
        result = run_story(transfers, query)
        answer = result["answer"]
        proof = list(result["proof"])
        if answer is None:
            # v1.4 abstentions: the ledger refused to certify a
            # number — an unmatched (over-) refund in the story, or
            # a scoped question whose scope matches more than one
            # lot (duplicate scope). Both are "the story does not
            # determine this", never a guessed number.
            missing = []
            if result.get("refund_issues"):
                missing.append(
                    "a refund in the story matches no earlier "
                    "transfer, so balances cannot be certified")
            if result.get("ambiguous_scope"):
                missing.append(
                    f"the scope of the question does not resolve "
                    f"to exactly one lot for {query.person}, so "
                    f"the scoped balance is ambiguous")
            return {
                "verdict": "unknown", "answer": None,
                "proof": proof,
                "complete": False, "status": "unknown",
                "missing": missing or [
                    f"balance for {query.person} is not determined "
                    f"by the story"],
                "evidence": [],
                "unusable_frames": [f.to_dict() for f in unusable],
            }
        # The answer also depends on frames that were NOT used: a negated
        # heuristic sentence ("John did not give Sarah $10") is exactly
        # why the balance is $0 rather than $10. If any unusable frame
        # came from the heuristic tier, the answer is a candidate, not
        # verified — the ledger math is exact, the parse is not.
        if any(f.certainty == "uncertain" for f in unusable):
            used_heuristic = True
        if unusable:
            proof.append(
                f"Note: {len(unusable)} frame(s) could not be used as "
                f"transfers and were ignored: "
                + "; ".join(f.source_text or f.what or "?"
                            for f in unusable))
        return {
            "verdict": "yes", "answer": answer, "proof": proof,
            "complete": True,
            "status": ("candidate_interpretation" if used_heuristic
                       else "verified"),
            "missing": [],
            "evidence": [{"source": "entity-ledger",
                          "statement": f"balance for {query.person}: "
                                       f"${answer:g}",
                          "kind": "computation"}],
            "unusable_frames": [f.to_dict() for f in unusable],
        }

    # -- balance yes/no questions (ledger path, closed-world) -----------
    def reason_balance_yes_no(self, frames: list[ConceptFrame],
                              query: ConceptFrame) -> dict:
        """'Does X have $N?' — answered from the ledger.

        Closed-world within the story as given: X's balance is the
        ledger total over the story's transfers, and the answer is
        "yes" iff that total equals the asked amount. If the story
        does not determine X's balance at all (X is never mentioned
        with a specific amount), the answer stays "unknown".
        """
        person = normalize_person(query.who)
        amount = query.quantity
        if person is None or amount is None:
            return {
                "verdict": "unknown", "answer": None, "proof": [],
                "complete": False, "status": "unknown",
                "missing": ["balance yes/no question has no person or "
                            "amount"],
                "evidence": [],
                "unusable_frames": [],
            }
        statements = [f for f in frames if f.kind != "query"]
        transfers, _, unusable, used_heuristic = split_story_frames(
            statements, allow_heuristic=True)
        if not _balance_determined(statements, person):
            return {
                "verdict": "unknown", "answer": None, "proof": [],
                "complete": False, "status": "unknown",
                "missing": [f"balance for {person} is not determined "
                            f"by the story"],
                "evidence": [],
                "unusable_frames": [f.to_dict() for f in unusable],
            }
        result = run_story(transfers, BalanceQuery(person=person))
        balance = result["answer"]
        if balance is None:
            # An unmatched (over-) refund poisons every balance in
            # the story (v1.4): the yes/no cannot be certified.
            return {
                "verdict": "unknown", "answer": None,
                "proof": list(result["proof"]),
                "complete": False, "status": "unknown",
                "missing": ["a refund in the story matches no "
                            "earlier transfer, so balances cannot "
                            "be certified"],
                "evidence": [],
                "unusable_frames": [f.to_dict() for f in unusable],
            }
        yes = float(balance) == float(amount)
        proof = list(result["proof"])
        proof.append(f"Asked: does {person} have ${amount:g}? "
                     f"Balance is ${balance:g} -> "
                     f"{'yes' if yes else 'no'}.")
        if any(f.certainty == "uncertain" for f in unusable):
            used_heuristic = True
        if unusable:
            proof.append(
                f"Note: {len(unusable)} frame(s) could not be used as "
                f"transfers and were ignored: "
                + "; ".join(f.source_text or f.what or "?"
                            for f in unusable))
        return {
            "verdict": "yes" if yes else "no",
            "answer": "yes" if yes else "no",
            "proof": proof,
            "complete": True,
            "status": ("candidate_interpretation" if used_heuristic
                       else "verified"),
            "missing": [],
            "evidence": [{"source": "entity-ledger",
                          "statement": f"balance for {person}: "
                                       f"${balance:g}",
                          "kind": "computation"}],
            "unusable_frames": [f.to_dict() for f in unusable],
        }

    # -- per-unit totals (knowledge -> calculation bridge) --------------
    def reason_per_unit_total(self, frames: list[ConceptFrame],
                              query: ConceptFrame) -> dict:
        """'How many <part> do N <things> have?' — N x per-unit count.

        The per-unit fact comes from a stated has-a frame or from the
        knowledge store (parsed with the same extractor). No fact
        means unknown — the count is never guessed.
        """
        thing = None
        for rel in query.relationships:
            if rel.get("rel") == "per_unit_of":
                thing = rel.get("target")
        found = find_per_unit_fact(frames, self.knowledge, thing,
                                   query.object)
        if found is None:
            return {
                "verdict": "unknown", "answer": None, "proof": [],
                "complete": False, "status": "unknown",
                "missing": [f"no per-unit fact for {thing or '?'} "
                            f"having {query.object or '?'}"],
                "evidence": [],
                "unusable_frames": [],
            }
        per_unit, evidence = found
        count = query.quantity
        total = count * per_unit
        total = int(total) if float(total).is_integer() else total
        proof = [f"One {thing} has {per_unit:g} {query.object}.",
                 f"{count:g} x {per_unit:g} = {total:g}."]
        return {
            "verdict": "yes", "answer": total, "proof": proof,
            "complete": True, "status": "verified",
            "missing": [],
            "evidence": evidence + [{"source": "local-calculator",
                                     "statement": f"{count:g} x "
                                                  f"{per_unit:g}",
                                     "kind": "computation"}],
            "unusable_frames": [],
        }

    # -- amount-paid questions (knowledge -> answer bridge) --------------
    def reason_amount_paid(self, frames: list[ConceptFrame],
                           query: ConceptFrame) -> dict:
        """'How much money did X pay?' — the amount of X's single
        payment in the story. Exactly one distinct amount answers it;
        zero or several means unknown (never a guessed sum)."""
        person = normalize_person(query.who)
        amounts, evidence = [], []
        for f in frames:
            if f.kind == "query":
                continue
            if normalize_person(f.who) != person:
                continue
            if f.what not in _AMOUNT_PAID_ACTIONS:
                continue
            if f.polarity != "positive" or f.quantity is None:
                continue
            if f.quantity not in amounts:
                amounts.append(f.quantity)
                evidence.extend(f.evidence)
        if len(amounts) != 1:
            return {
                "verdict": "unknown", "answer": None, "proof": [],
                "complete": False, "status": "unknown",
                "missing": ["no single payment amount for "
                            f"{person or '?'} in the story"],
                "evidence": [],
                "unusable_frames": [],
            }
        amount = amounts[0]
        return {
            "verdict": "yes", "answer": amount,
            "proof": [f"{person} paid ${amount:g}."],
            "complete": True,
            "status": "candidate_interpretation",
            "missing": [],
            "evidence": evidence,
            "unusable_frames": [],
        }

    def _instantiate_rules(self, frames: list[ConceptFrame],
                           facts: list[str]) -> list:
        """Rule frames -> adapter rules, instantiated against the facts.

        A rule frame says "every A is a B" ("If someone is human,
        they are mortal"). The adapter's prover matches literal fact
        strings, so each rule is instantiated for every fact that
        matches its antecedent: is(socrates,human) + the rule gives
        (["is(socrates,human)"], "is(socrates,mortal)"). That is
        universal instantiation — sound, deterministic, and it keeps
        the rule's provenance in the frame's evidence.
        """
        instantiated = []
        for f in frames:
            if f.kind != "rule":
                continue
            antecedent = (f.object or "").strip().lower().replace(" ", "_")
            consequent = None
            for rel in f.relationships:
                if rel.get("rel") == "implies":
                    consequent = rel.get("target")
            if not antecedent or not consequent:
                continue
            consequent = consequent.strip().lower().replace(" ", "_")
            for fact in facts:
                m = re.fullmatch(r"is\(([^,]+),([^,]+)\)", fact)
                if m and m.group(2) == antecedent:
                    who = m.group(1)
                    instantiated.append(
                        ([fact], f"is({who},{consequent})"))
        return instantiated

    # -- yes/no goals (propositional path) --------------------------------
    def reason_goal(self, frames: list[ConceptFrame], goal: str,
                    rules: list | None = None) -> dict:
        statement_frames = [f for f in frames if f.kind != "query"]
        facts, blocked, used_heuristic = frames_to_facts(statement_frames)
        all_rules = list(rules or []) + self._instantiate_rules(
            statement_frames, facts)
        result = self.reasoner.prove(facts, all_rules, goal)
        verdict = result["verdict"]
        proof = [f"{', '.join(t['premises'])} -> {t['conclusion']}"
                 for t in result["trace"]]
        if not proof:
            proof = [f"premises: {facts}" if facts else
                     "no usable premises"]
        complete = bool(result["complete"]) and verdict != "unknown"
        if verdict == "unknown":
            # Adjective is/state equivalence: "Is iron strong?" asks
            # state(iron,strong), but a rule concludes is(iron,strong)
            # ("If something is metal, it is strong"). For an adjective
            # complement the two predicates ask the same thing, so a
            # proof of the equivalent form settles the goal. The proof
            # says so explicitly — the equivalence is shown, not hidden.
            alt_goal = _adjective_alt_goal(goal)
            if alt_goal is not None:
                alt = self.reasoner.prove(facts, all_rules, alt_goal)
                if alt["verdict"] != "unknown":
                    verdict = alt["verdict"]
                    proof = [f"{', '.join(t['premises'])} -> "
                             f"{t['conclusion']}"
                             for t in alt["trace"]] or proof
                    proof.append(f"Note: '{goal}' and '{alt_goal}' ask "
                                 f"the same thing for the adjective "
                                 f"{goal.rsplit(',', 1)[-1][:-1]}.")
                    complete = bool(alt["complete"])
        if verdict == "unknown":
            # Adjective antonyms: a stated state settles the opposite
            # state as "no" — "The light is on" proves "Is the light
            # off?" is no. Only fires on state(...) facts, never on
            # actions (buying does not imply selling).
            antonym_proof = self._state_antonym(facts, goal)
            if antonym_proof is not None:
                verdict = "no"
                proof = antonym_proof
                complete = True
        if verdict == "unknown":
            # Closed-world near-miss over the story's money transfers:
            # a yes/no transfer question is settled by the story iff
            # it names the SAME action (verb, after canonicalization)
            # as a stated transfer and matches it on at least two of
            # (giver, recipient, amount) — it asks about a transfer
            # the story already accounts for, with one slot changed.
            # A goal naming a different verb asks about a different
            # kind of event the story says nothing about (giving is
            # not paying), and a goal sharing at most one slot asks
            # about a different, unmentioned transfer: in both cases
            # the honest answer stays unknown. (Audit 2026-10-27:
            # fresh-006/078 fired here on a verb mismatch and
            # answered "no" where the truth is "unknown".)
            cw_proof = self._closed_world_transfer(goal, frames)
            if cw_proof is not None:
                verdict = "no"
                proof = cw_proof
                complete = True
        missing = list(blocked)
        if verdict == "unknown":
            missing.append(f"goal '{goal}' is not entailed by the frames")
        return {
            "verdict": verdict, "answer": verdict, "proof": proof,
            "complete": complete,
            "status": ("candidate_interpretation" if used_heuristic
                       else "verified_logic") if complete else "unknown",
            "missing": missing,
            "evidence": [{"source": "supplied-premises",
                          "statement": str(facts), "kind": "premise"}],
            "unusable_frames": [],
        }

    def _state_antonym(self, facts: list[str], goal: str
                       ) -> list[str] | None:
        """Adjective-antonym proof for "no", or None.

        Only for goals of the form ``state(who, adjective)``: if the
        facts contain ``state(who, opposite)`` for the adjective's
        antonym, the goal is false. A negated state fact ("not
        state(light,on)") does NOT settle the opposite — absence of
        evidence for "on" is not evidence for "off".
        """
        m = re.fullmatch(r"state\(([^,]+),([^,]+)\)", goal or "")
        if not m:
            return None
        who, adjective = m.group(1), m.group(2)
        opposite = ANTONYM_ADJECTIVES.get(adjective)
        if opposite is None:
            return None
        stated = f"state({who},{opposite})"
        if stated in facts:
            return [
                f"Stated: {stated}.",
                f"{adjective} and {opposite} are opposites, so "
                f"{goal} is false.",
            ]
        return None

    def _closed_world_transfer(self, goal: str,
                               frames: list[ConceptFrame]
                               ) -> list[str] | None:
        """Near-miss closed-world: a proof for "no", or None.

        Only for fully-specified money-transfer goals
        give/send/pay(giver, recipient, amount). The goal is settled
        iff it names the SAME action as a stated positive transfer
        and matches it on at least two of the three slots: the story
        accounts for the funds (same giver+amount, different
        recipient) or the channel (same giver+recipient, different
        amount), and the asked transfer is not the stated one.

        The verb is read from the FRAMES, not the fact strings:
        ``frame_to_fact`` canonicalizes give/send/pay to "give" (the
        ledger treats them as the same money movement), so by the
        time the reasoner sees facts the verb is gone — and a
        giving is not a paying. "Receive" arrives as "give" (the
        parser canonicalizes it that way in both story and question
        frames), so receive-questions still join up. A goal naming
        a different verb asks about a different kind of event the
        story says nothing about, so it is NOT ruled out and the
        verdict stays unknown. A goal matching on at most one slot
        is a different, unmentioned transfer — return None so the
        verdict stays unknown instead of a guessed "no".
        """
        m = _MONEY_FACT_RE.match(goal or "")
        if not m:
            return None
        g_giver, g_recip = m.group(2).lower(), m.group(3).lower()
        g_amt = float(m.group(4))
        goal_verb = None
        for f in frames:
            if f.kind == "query" and _is_yes_no(f):
                goal_verb = ("give" if f.what == "receive"
                             else (f.what or "").lower()) or None
                break
        if goal_verb is None:
            # No query frame carries the verb (externally supplied
            # goal): the action cannot be established, so nothing
            # here rules the transfer out.
            return None
        stated = []
        for f in frames:
            if f.kind in ("query", "rule"):
                continue
            fact = frame_to_fact(f)
            if fact is None:
                continue
            sm = _MONEY_FACT_RE.match(fact)
            if not sm:
                continue
            verb = ("give" if f.what == "receive"
                    else (f.what or "").lower())
            stated.append((verb, sm.group(2).lower(),
                           sm.group(3).lower(), float(sm.group(4)),
                           fact))
        if not stated:
            return None
        for (s_verb, s_giver, s_recip, s_amt, raw) in stated:
            if (s_giver, s_recip, s_amt) == (g_giver, g_recip, g_amt):
                return None  # entailed; prove() would have said yes
            if s_verb != goal_verb:
                # Different action: the story says nothing about it.
                continue
            shared = [g_giver == s_giver, g_recip == s_recip,
                      g_amt == s_amt]
            if sum(shared) >= 2:
                matched = ("giver and amount" if shared[0] and shared[2]
                           else "giver and recipient"
                           if shared[0] and shared[1]
                           else "recipient and amount")
                return [
                    "Story transfers: "
                    + "; ".join(s[4] for s in stated) + ".",
                    f"The asked transfer {goal} matches the stated "
                    f"transfer {raw} on {matched} but differs on the "
                    f"other slot; within the story as given, the "
                    f"transfer in question went as stated, not as "
                    f"asked.",
                ]
        return None

    # -- unified entry point ----------------------------------------------
    def reason(self, frames: list[ConceptFrame],
               goal: str | None = None,
               rules: list | None = None,
               ablations: set | None = None) -> dict:
        """Route frames to the right inference: balance query, yes/no
        goal, or — when there is nothing to prove — an honest analysis.

        ``ablations`` (eval-harness use): ``{"reasoner"}`` disables the
        propositional yes/no path — the goal returns ``unknown`` with an
        explicit missing reason instead of a proof. The balance (ledger)
        path is a different module and is not affected.
        """
        ablations = ablations or set()
        query = find_query(frames)
        if query is not None and query.what == "balance":
            # A balance yes/no ("Does X have $N?") is a ledger
            # question, not a propositional goal — and it is NOT
            # disabled by the "reasoner" ablation, which only covers
            # the propositional yes/no path.
            if _is_yes_no(query):
                return self.reason_balance_yes_no(frames, query)
            return self.reason_balance(frames)
        if query is not None and query.what == "per_unit_total":
            return self.reason_per_unit_total(frames, query)
        if query is not None and query.what == "amount_paid":
            return self.reason_amount_paid(frames, query)
        if "reasoner" in ablations and (
                goal is not None or (query is not None and any(
                    r.get("rel") == "asks_whether"
                    for r in query.relationships))):
            return {
                "verdict": "unknown", "answer": None, "proof": [],
                "complete": False, "status": "unknown",
                "missing": ["symbolic reasoner disabled by ablation"],
                "evidence": [],
                "unusable_frames": [],
            }
        if query is not None and any(
                r.get("rel") == "asks_whether"
                for r in query.relationships):
            goal_fact = goal or goal_frame_to_fact(query)
            if goal_fact is None:
                return {
                    "verdict": "unknown", "answer": None, "proof": [],
                    "complete": False, "status": "unknown",
                    "missing": ["yes/no question could not be parsed "
                                "into a goal fact"],
                    "evidence": [],
                    "unusable_frames": [query.to_dict()],
                }
            return self.reason_goal(frames, goal_fact, rules)
        if goal is not None:
            return self.reason_goal(frames, goal, rules)
        # Routed answers: a calculation frame already carries its
        # computed value, and a retrieved definition frame already
        # carries its meaning. They are answers, not questions — the
        # reasoner returns them instead of an analysis.
        for f in frames:
            if f.kind == "calculation" and f.quantity is not None:
                return {
                    "verdict": "yes", "answer": f.quantity,
                    "proof": [f"{f.object} = {f.quantity:g}"],
                    "complete": True, "status": "verified",
                    "missing": [], "evidence": list(f.evidence),
                    "unusable_frames": [],
                }
        for f in frames:
            if f.kind == "definition" and f.certainty == "known":
                meaning = None
                for rel in f.relationships:
                    if rel.get("rel") == "defined_as":
                        meaning = rel.get("target")
                return {
                    "verdict": "yes",
                    "answer": {"term": f.object, "meaning": meaning},
                    "proof": [f"{f.object}: {meaning}"],
                    "complete": True, "status": "retrieved",
                    "missing": [], "evidence": list(f.evidence),
                    "unusable_frames": [],
                }
        # No query and no goal: report the frames, prove nothing.
        return {
            "verdict": "unknown", "answer": None,
            "proof": [f"frame: {f.source_text or f.what}"
                      for f in frames],
            "complete": False, "status": "unknown",
            "missing": ["no question or goal supplied"],
            "evidence": [],
            "unusable_frames": [],
        }
