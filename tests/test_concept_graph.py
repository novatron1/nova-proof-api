"""Tests for the explicit concept graph (nova/semantic/graph.py).

Phase 2 gap-closure, additive only: this suite covers graph
construction from ConceptFrames, node/edge typing, JSON round-trip,
definition-expansion depth/cycle safety, and the query API. It does
not touch the evaluated pipeline, harness, or eval sets.
"""

import json
import unittest

from nova.semantic.extract import parse_text_to_frames
from nova.semantic.frame import ConceptFrame
from nova.semantic.graph import (ConceptEdge, ConceptGraph, ConceptNode,
                                 DEFAULT_EXPANSION_DEPTH)
from nova.semantic.lexicon import Lexicon


def _transfer(who, what, recipient, obj, qty, polarity="positive",
              when=None, where=None, why=None):
    return ConceptFrame(kind="transfer", who=who, what=what,
                        recipient=recipient, object=obj, quantity=qty,
                        units="dollars", when=when, where=where, why=why,
                        polarity=polarity, certainty="known",
                        status="verified")


class TestConstructionFromFrames(unittest.TestCase):
    def test_money_story_nodes_and_edges(self):
        frames = parse_text_to_frames(
            "Marcus gave John $20. John gave Sarah $10.")
        g = ConceptGraph.from_frames(frames, label="money-story")
        self.assertEqual(sorted(n.label for n in g.actors()),
                         ["John", "Marcus", "Sarah"])
        # Two distinct "give" events -> two distinct action nodes.
        self.assertEqual(len(g.actions()), 2)
        self.assertTrue(all(n.label == "give" for n in g.actions()))
        self.assertEqual([n.label for n in g.objects()], ["dollars"])
        rels = sorted(e.rel for e in g.edges)
        self.assertIn("agent", rels)
        self.assertIn("patient", rels)
        self.assertIn("recipient", rels)
        self.assertIn("quantity", rels)
        # Actors join up across sentences: John is one node.
        self.assertEqual(len(g.find_nodes("John", "actor")), 1)

    def test_actor_dedup_across_frames(self):
        frames = [_transfer("Marcus", "give", "John", "dollars", 20),
                  _transfer("Marcus", "give", "Sarah", "dollars", 5)]
        g = ConceptGraph.from_frames(frames)
        self.assertEqual(len(g.find_nodes("Marcus", "actor")), 1)
        self.assertEqual(len(g.actions()), 2)

    def test_unknown_slots_produce_nothing(self):
        frame = ConceptFrame(kind="event", who=None, what="rain",
                             object=None, quantity=None)
        g = ConceptGraph.from_frames([frame])
        self.assertEqual(len(g.actors()), 0)
        self.assertEqual(len(g.objects()), 0)
        self.assertEqual(len(g.actions()), 1)
        self.assertEqual(g.edges, [])

    def test_condition_nodes_and_temporal_edges(self):
        frame = _transfer("Marcus", "give", "John", "dollars", 20,
                          when="yesterday", where="the studio",
                          why="his birthday")
        g = ConceptGraph.from_frames([frame])
        conds = {n.label: n.attrs.get("slot") for n in g.conditions()}
        self.assertEqual(conds, {"yesterday": "when",
                                 "the studio": "where",
                                 "his birthday": "why"})
        action = g.actions()[0]
        rels = {e.rel for e in g.edges_from(action.id)}
        self.assertIn("temporal", rels)
        self.assertIn("condition", rels)

    def test_negation_kept_as_polarity_edge(self):
        frame = _transfer("Marcus", "give", "John", "dollars", 20,
                          polarity="negative")
        g = ConceptGraph.from_frames([frame])
        action = g.actions()[0]
        self.assertEqual(action.attrs["polarity"], "negative")
        pol = [e for e in g.edges_from(action.id) if e.rel == "polarity"]
        self.assertTrue(pol)
        self.assertEqual(pol[0].attrs["value"], "negative")

    def test_frame_relationships_become_relationship_nodes(self):
        frame = ConceptFrame(
            kind="definition", who="bicycle", what="is",
            object="a wheeled vehicle",
            relationships=[{"rel": "is_a", "target": "a wheeled vehicle"},
                           {"rel": "defined_as",
                            "target": "a wheeled vehicle"}],
            status="verified")
        g = ConceptGraph.from_frames([frame])
        self.assertEqual(
            sorted(n.label for n in g.relationships()),
            ["defined_as", "is_a"])
        rel_node = g.find_nodes("is_a", "relationship")[0]
        self.assertEqual(rel_node.attrs["target"], "a wheeled vehicle")

    def test_calculation_frame_yields_consequence(self):
        frame = ConceptFrame(kind="calculation", what="multiply",
                             object="dozen", quantity=24, units="items",
                             status="verified")
        g = ConceptGraph.from_frames([frame])
        self.assertEqual(len(g.consequences()), 1)
        cons = g.consequences()[0]
        self.assertEqual(cons.attrs["quantity"], 24)
        action = g.actions()[0]
        self.assertTrue(any(e.rel == "causation" and e.target == cons.id
                            for e in g.edges_from(action.id)))

    def test_add_frames_appends(self):
        g = ConceptGraph.from_frames(
            [_transfer("Marcus", "give", "John", "dollars", 20)])
        g.add_frames([_transfer("John", "give", "Sarah", "dollars", 10)])
        self.assertEqual(len(g.actions()), 2)
        self.assertEqual(len(g.actors()), 3)


class TestQueries(unittest.TestCase):
    def setUp(self):
        frames = [_transfer("Marcus", "give", "John", "dollars", 20,
                            when="yesterday"),
                  _transfer("John", "give", "Sarah", "dollars", 10,
                            when="today")]
        self.g = ConceptGraph.from_frames(frames)

    def test_path_between_actor_and_recipient(self):
        marcus = self.g.find_nodes("Marcus", "actor")[0]
        sarah = self.g.find_nodes("Sarah", "actor")[0]
        path = self.g.path_between(marcus.id, sarah.id)
        self.assertIsNotNone(path)
        labels = [self.g.nodes[nid].label for nid in path]
        self.assertEqual(labels[0], "Marcus")
        self.assertEqual(labels[-1], "Sarah")
        self.assertIn("give", labels)
        # Directed: no path back from Sarah to Marcus.
        self.assertIsNone(self.g.path_between(sarah.id, marcus.id))

    def test_path_between_unrelated_is_none(self):
        g = ConceptGraph.from_frames(
            [_transfer("Marcus", "give", "John", "dollars", 20),
             _transfer("Alice", "give", "Bob", "dollars", 5)])
        alice = g.find_nodes("Alice", "actor")[0]
        marcus = g.find_nodes("Marcus", "actor")[0]
        self.assertIsNone(g.path_between(alice.id, marcus.id))

    def test_neighbors_filtered_by_relation(self):
        give = self.g.actions()[0]
        agents = self.g.neighbors(give.id, rel="agent", direction="in")
        self.assertEqual([n.label for n in agents], ["Marcus"])
        patients = self.g.neighbors(give.id, rel="patient")
        self.assertEqual([n.label for n in patients], ["dollars"])

    def test_subgraph_by_condition(self):
        sub = self.g.subgraph_by_condition("yesterday")
        self.assertEqual([n.label for n in sub.conditions()],
                         ["yesterday"])
        self.assertEqual(len(sub.actions()), 1)
        self.assertEqual(sorted(n.label for n in sub.actors()),
                         ["John", "Marcus"])
        # The "today" action and Sarah stay out.
        self.assertEqual(sub.find_nodes("Sarah", "actor"), [])
        self.assertEqual(sub.find_nodes("today", "condition"), [])
        # Absent condition -> empty graph, never a guess.
        empty = self.g.subgraph_by_condition("never")
        self.assertEqual(len(empty.nodes), 0)

    def test_find_contradictions_polarity(self):
        frames = [_transfer("Marcus", "give", "John", "dollars", 20),
                  _transfer("Marcus", "give", "John", "dollars", 20,
                            polarity="negative")]
        g = ConceptGraph.from_frames(frames)
        contra = g.find_contradictions()
        self.assertEqual(len(contra), 1)
        self.assertEqual(contra[0]["type"], "polarity")
        self.assertEqual(contra[0]["actor"], "Marcus")
        self.assertEqual(contra[0]["action"], "give")

    def test_find_contradictions_quantity(self):
        frames = [_transfer("Marcus", "give", "John", "dollars", 20),
                  _transfer("Marcus", "give", "John", "dollars", 10)]
        g = ConceptGraph.from_frames(frames)
        contra = g.find_contradictions()
        self.assertEqual(len(contra), 1)
        self.assertEqual(contra[0]["type"], "quantity")
        self.assertIn("20", contra[0]["detail"])
        self.assertIn("10", contra[0]["detail"])

    def test_agreement_is_not_a_contradiction(self):
        frames = [_transfer("Marcus", "give", "John", "dollars", 20),
                  _transfer("Marcus", "give", "John", "dollars", 20)]
        g = ConceptGraph.from_frames(frames)
        self.assertEqual(g.find_contradictions(), [])

    def test_explicit_causation_edge(self):
        g = ConceptGraph()
        a = g.add_node("action", "push")
        b = g.add_node("action", "fall")
        self.assertTrue(g.add_causation(a, b))
        self.assertEqual(g.edges_from(a)[0].rel, "causation")
        # Duplicate edge is a no-op.
        self.assertFalse(g.add_causation(a, b))


class TestSerialization(unittest.TestCase):
    def test_json_round_trip_exact(self):
        # The two frames ARE the same claim with opposite polarity,
        # so exactly one contradiction survives the round trip.
        frames = [_transfer("Marcus", "give", "John", "dollars", 20,
                            when="yesterday", polarity="negative"),
                  _transfer("Marcus", "give", "John", "dollars", 20)]
        g = ConceptGraph.from_frames(frames, label="rt")
        self.assertEqual(len(g.find_contradictions()), 1)
        g2 = ConceptGraph.from_json(g.to_json())
        self.assertEqual(g.to_dict(), g2.to_dict())
        # Round-tripped graph still answers queries.
        self.assertEqual(len(g2.actions()), 2)
        self.assertEqual(len(g2.find_contradictions()), 1)

    def test_dict_round_trip_preserves_expanded_terms(self):
        g = ConceptGraph()
        g._expanded_terms.add("bicycle")
        g2 = ConceptGraph.from_dict(g.to_dict())
        self.assertEqual(g2._expanded_terms, {"bicycle"})

    def test_merge_remaps_ids_without_collision(self):
        g1 = ConceptGraph.from_frames(
            [_transfer("Marcus", "give", "John", "dollars", 20)])
        g2 = ConceptGraph.from_frames(
            [_transfer("Alice", "give", "Bob", "dollars", 5)])
        id_map = g1.merge(g2)
        self.assertEqual(len(g1.actions()), 2)
        self.assertEqual(len(g1.actors()), 4)
        self.assertEqual(set(id_map), set(g2.nodes))
        self.assertTrue(all(v in g1.nodes for v in id_map.values()))

    def test_invalid_node_type_rejected(self):
        g = ConceptGraph()
        with self.assertRaises(ValueError):
            g.add_node("nope", "x")

    def test_node_and_edge_dataclass_round_trip(self):
        n = ConceptNode(id="n1", type="actor", label="Marcus",
                        attrs={"x": 1})
        self.assertEqual(ConceptNode.from_dict(n.to_dict()), n)
        e = ConceptEdge(source="n1", target="n2", rel="agent")
        self.assertEqual(ConceptEdge.from_dict(e.to_dict()), e)


class _FakeCyclicLexicon:
    """decompose() returns a self-referential tree: A -> B -> A."""

    def decompose(self, term, depth=3):
        if depth < 1:
            return None
        return {
            "term": term.lower(), "sense_no": 1, "pos": "n",
            "gloss": f"a {term} thing", "source": "fake",
            "frames": [{"kind": "fact", "who": term.lower(),
                        "what": "is", "object": f"a {term} thing",
                        "relationships": [],
                        "polarity": "positive",
                        "certainty": "known", "status": "verified"}],
            "components": [
                {"term": "b" if term.lower() == "a" else "a",
                 "sense_no": 1, "pos": "n",
                 "gloss": "the other thing", "source": "fake",
                 "frames": [],
                 "components": [
                     {"term": term.lower(), "sense_no": 1, "pos": "n",
                      "gloss": f"a {term} thing", "source": "fake",
                      "frames": [], "components": []}]},
            ],
        }


class TestDefinitionExpansion(unittest.TestCase):
    def test_expand_real_term_from_store(self):
        lex = Lexicon()
        g = ConceptGraph()
        term_id = g.expand_definition("bicycle", lex, depth=2)
        self.assertIsNotNone(term_id)
        term_node = g.nodes[term_id]
        self.assertEqual(term_node.type, "object")
        self.assertTrue(term_node.attrs.get("defined_term"))
        self.assertIn("vehicle", term_node.attrs.get("gloss", ""))
        # The definition's frames entered the graph as actions.
        self.assertTrue(any(n.label == "has" for n in g.actions()))
        # Component terms linked with expands edges.
        self.assertTrue(any(
            e.rel == "expands" and e.source == term_id
            for e in g.edges))
        # Defined-as links from the term to its definition actions.
        self.assertTrue(any(
            e.rel == "defined_as" and e.source == term_id
            for e in g.edges))

    def test_expand_unknown_term_returns_none(self):
        lex = Lexicon()
        g = ConceptGraph()
        self.assertIsNone(g.expand_definition("zzqx-no-such-word", lex))
        self.assertEqual(len(g.nodes), 0)

    def test_expand_twice_is_idempotent(self):
        lex = Lexicon()
        g = ConceptGraph()
        first = g.expand_definition("bicycle", lex, depth=2)
        size = (len(g.nodes), len(g.edges))
        second = g.expand_definition("bicycle", lex, depth=2)
        self.assertEqual(first, second)
        self.assertEqual((len(g.nodes), len(g.edges)), size)

    def test_expansion_depth_limit(self):
        lex = Lexicon()
        g1 = ConceptGraph()
        g1.expand_definition("bicycle", lex, depth=1)
        g2 = ConceptGraph()
        g2.expand_definition("bicycle", lex, depth=2)
        # Depth 1: no component expansion; depth 2: components added.
        self.assertFalse(any(e.rel == "expands" for e in g1.edges))
        self.assertTrue(any(e.rel == "expands" for e in g2.edges))

    def test_cyclic_tree_terminates(self):
        g = ConceptGraph()
        term_id = g.expand_definition(
            "a", _FakeCyclicLexicon(),
            depth=DEFAULT_EXPANSION_DEPTH)
        self.assertIsNotNone(term_id)
        # A -> B -> A must stop: at most the two distinct terms.
        terms = [n.label for n in g.objects()
                 if n.attrs.get("defined_term")]
        self.assertEqual(sorted(set(terms)), ["a", "b"])

    def test_cyclic_tree_depth_cap(self):
        # Even with a huge depth budget the cycle guard bounds it.
        g = ConceptGraph()
        g.expand_definition("a", _FakeCyclicLexicon(), depth=50)
        self.assertLessEqual(len(g.nodes), 12)


if __name__ == "__main__":
    unittest.main()
