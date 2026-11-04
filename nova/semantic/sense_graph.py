"""Sense graph + external lexicon — merged from NOVA Cognitive
Adapter v1.2 (Semantic Graph) on 2026-11-02. See MERGE_MAP.md (a)+(b).

What v1.2 had that this repo lacked:

* ``load_external_lexicon`` — load an externally supplied JSON sense
  dictionary with strict shape validation. A malformed entry raises
  ValueError; senses are NEVER fabricated to fill a gap.
* A separate sense graph whose edges keep ``has_sense``, ``synonym``
  and ``antonym`` as DISTINCT relations — an antonym is never merged
  into, or rendered as, a synonym.

Conformance: the graph is a plain dict of nodes/edges (v1.2 shape).
``to_concept_graph`` bridges it into this repo's shared ConceptGraph
format (word/sense nodes become ``object`` nodes; the three sense
relations are preserved as edge rels). Nothing here replaces the
ConceptFrame schema or the production Lexicon; the production bridge
(``sense_graph_for_terms``) builds the graph FROM the production
Lexicon's real senses/synonyms/antonyms.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


# ---------------------------------------------------------------------------
# (a) External lexicon loading with shape validation (ported from v1.2)
# ---------------------------------------------------------------------------

def load_external_lexicon(path) -> dict:
    """Load a user-provided sense dictionary. Never invent senses.

    Format: a JSON object mapping each term to a non-empty list of
    senses; each sense is an object with a non-empty string
    ``meaning`` and optional ``synonyms`` / ``antonyms`` / ``cues``
    lists of strings. Any deviation raises ValueError.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Lexicon must be an object")
    for term, senses in raw.items():
        if not isinstance(term, str) or not isinstance(senses, list) \
                or not senses:
            raise ValueError("Invalid term or empty senses")
        for sense in senses:
            if not isinstance(sense, dict) \
                    or not isinstance(sense.get("meaning"), str) \
                    or not sense["meaning"].strip():
                raise ValueError("Sense must have a meaning")
            for field in ("synonyms", "antonyms", "cues"):
                if field in sense and (
                        not isinstance(sense[field], list)
                        or not all(isinstance(v, str)
                                   for v in sense[field])):
                    raise ValueError("Invalid sense relation")
    return raw


def lexical_senses(text: str, lexicon: dict) -> list[dict]:
    """v1.2 lexical analysis over an external lexicon dict: for each
    lexicon term present in ``text`` (with basic inflection variants),
    return its senses with the context cues each sense hits, the
    contextual candidate meanings, and an ambiguity flag. Candidate
    senses are preserved, never conflated."""
    words = set(re.findall(r"[a-z]+", text.lower()))
    results = []
    for word, senses in lexicon.items():
        variants = {word, word + "s", word + "ed", word + "ing"}
        if word == "run":
            variants |= {"runs", "running", "ran"}
        if word == "give":
            variants |= {"gave", "gives", "given"}
        if not words.intersection(variants):
            continue
        entries = []
        for s in senses:
            entries.append({
                "meaning": s["meaning"],
                "synonyms": s.get("synonyms", []),
                "antonyms": s.get("antonyms", []),
                "context_hits": sorted(
                    words.intersection(s.get("cues", []))),
            })
        strongest = max((len(e["context_hits"]) for e in entries),
                        default=0)
        winners = [e["meaning"] for e in entries
                   if strongest and len(e["context_hits"]) == strongest]
        results.append({"word": word, "senses": entries,
                        "contextual_candidates": winners,
                        "ambiguous": len(winners) != 1})
    return results


# ---------------------------------------------------------------------------
# (b) The sense graph: has_sense / synonym / antonym kept distinct
# ---------------------------------------------------------------------------

def build_sense_graph(lexical: list[dict]) -> dict:
    """Expose alternative senses separately, never conflate antonyms
    and synonyms. ``lexical`` is a list of entries in the shape
    ``lexical_senses`` (or ``sense_graph_for_terms``) returns."""
    nodes: list[dict] = []
    edges: list[dict] = []

    def _ensure_word_node(term: str, kind: str = "word"):
        rid = f"word:{term}"
        if not any(n["id"] == rid for n in nodes):
            nodes.append({"id": rid, "kind": kind, "label": term})
        return rid

    for entry in lexical:
        term = entry["word"]
        _ensure_word_node(term)
        for i, sense in enumerate(entry["senses"]):
            sid = f"sense:{term}:{i}"
            nodes.append({"id": sid, "kind": "sense",
                          "label": sense["meaning"],
                          "context_hits": sense.get("context_hits", [])})
            edges.append({"from": f"word:{term}", "to": sid,
                          "relation": "has_sense"})
            for relation in ("synonyms", "antonyms"):
                for related in sense.get(relation, []):
                    rid = _ensure_word_node(related, "related_word")
                    edges.append({"from": sid, "to": rid,
                                  "relation": relation[:-1]})
    return {"nodes": nodes, "edges": edges,
            "note": "Relationships are lexical candidates, not "
                    "evidence that a sense is true in context."}


def sense_graph_for_terms(terms: list[str], lexicon=None,
                          context: str = "") -> dict:
    """Build a sense graph for ``terms`` from the production Lexicon:
    every WordNet/Wiktionary sense becomes a ``has_sense`` edge, and
    the lexicon's synonym/antonym relations attach to the
    contextually disambiguated sense when one is chosen (otherwise
    to the first sense, marked as un-disambiguated). An absent
    lexicon or unknown term yields an empty graph, never an error
    and never an invented sense."""
    if lexicon is None:
        try:
            from .lexicon import default_lexicon
            lexicon = default_lexicon()
        except Exception:  # noqa: BLE001 - no lexicon, empty graph
            return {"nodes": [], "edges": [],
                    "note": "No lexicon available."}
    entries = []
    words_in_context = set(re.findall(r"[a-z]+", context.lower()))
    for term in terms:
        try:
            senses = lexicon.senses(term)
            syns = lexicon.synonyms(term)
            ants = lexicon.antonyms(term)
            chosen = lexicon.disambiguate(term, context=context)
        except Exception:  # noqa: BLE001 - per-term failure is empty
            continue
        if not senses:
            continue
        chosen_no = (chosen.get("sense_no")
                     if isinstance(chosen, dict) else None)
        sense_entries = []
        for s in senses:
            is_chosen = (chosen_no is not None
                         and s.get("sense_no") == chosen_no)
            sense_entries.append({
                "meaning": s.get("gloss", ""),
                "synonyms": syns if is_chosen else [],
                "antonyms": ants if is_chosen else [],
                "context_hits": sorted(
                    words_in_context.intersection(
                        re.findall(r"[a-z]+",
                                   (s.get("gloss") or "").lower()))),
                "pos": s.get("pos"),
                "sense_no": s.get("sense_no"),
                "source": s.get("source"),
            })
        if chosen_no is None and sense_entries:
            # No disambiguation: relations attach to the first sense
            # but are flagged, so nobody reads them as chosen-sense
            # relations.
            sense_entries[0]["synonyms"] = syns
            sense_entries[0]["antonyms"] = ants
            sense_entries[0]["relations_undisambiguated"] = True
        entries.append({"word": term, "senses": sense_entries,
                        "contextual_candidates": [],
                        "ambiguous": chosen_no is None})
    return build_sense_graph(entries)


def to_concept_graph(graph: dict):
    """Bridge a sense-graph dict into this repo's shared ConceptGraph
    format. Word and sense nodes become ``object`` nodes (labels and
    provenance kept in attrs); ``has_sense`` / ``synonym`` /
    ``antonym`` edges keep their relation names, so the distinction
    survives the bridge."""
    from .graph import ConceptGraph
    cg = ConceptGraph(label="sense-graph")
    ids: dict[str, str] = {}
    for node in graph.get("nodes", []):
        attrs = {k: v for k, v in node.items()
                 if k not in ("id", "label")}
        ids[node["id"]] = cg.add_node(
            "object", node["label"], attrs=attrs, unique=False)
    for edge in graph.get("edges", []):
        src, dst = ids.get(edge["from"]), ids.get(edge["to"])
        if src is None or dst is None or src == dst:
            continue
        cg.add_edge(src, dst, edge["relation"])
    return cg
