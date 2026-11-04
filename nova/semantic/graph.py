"""Explicit concept graphs for the NOVA Cognitive Adapter.

Phase 2 gap-closure (additive only): everything else in Phase 2 works
on flat lists of ``ConceptFrame`` objects. A graph makes the structure
those frames already carry *explicit* — typed nodes, labelled edges,
paths, subgraphs, contradiction checks — so later phases (and the
supervisory reasoner) can query relationships instead of re-scanning
frame lists.

Design rules (same honesty rules as ``frame.py``):

* The graph is built FROM the shared ``ConceptFrame`` schema
  (``nova/semantic/frame.py``). No second frame schema is invented:
  ``ConceptGraph.from_frames(frames)`` is the only construction path
  for story/question frames, and definition expansion reuses
  ``Lexicon.decompose`` trees, whose ``frames`` entries are already
  ``ConceptFrame`` dicts.
* Unknown slots stay unknown: a frame slot that is ``None`` produces
  no node and no edge — never a guessed node.
* Negation is first-class: a negated frame keeps its polarity on the
  action node and on a dedicated ``polarity`` edge, so contradiction
  detection can see it instead of silently dropping it.
* Everything is deterministic: node ids are assigned in insertion
  order, ``to_dict``/``from_dict`` round-trip exactly, and no live
  model or store call happens here (a lexicon is passed in by the
  caller for definition expansion).

Node types (closed): ``actor``, ``action``, ``object``,
``condition``, ``relationship``, ``consequence``.

Edge relations (closed for frame-derived edges): ``agent``,
``patient``, ``recipient``, ``quantity``, ``polarity``,
``temporal``, ``causation``, ``condition``, ``defined_as``,
``is_a``, ``has_a``, ``expands``. ``causation`` edges are only
created when a caller adds them explicitly (frames carry no
causation claim on their own) or when a definition frame states one;
nothing here infers causation from mere sequence.

This module is deliberately NOT wired into the evaluated NOVA path
(``pipeline.py`` / ``production.py`` / ``eval/*`` are untouched).
It is a standalone structure the rest of the system can query.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field

from .frame import ConceptFrame

# ---------------------------------------------------------------------------
# Vocabularies (closed where honesty depends on them)
# ---------------------------------------------------------------------------

NODE_TYPES = ("actor", "action", "object", "condition",
              "relationship", "consequence")

# Relations a frame can produce on its own, plus the two expansion
# relations definition decomposition adds. "causation" is in the set
# but is only ever added explicitly — see module docstring.
EDGE_RELS = ("agent", "patient", "recipient", "quantity", "polarity",
             "temporal", "causation", "condition", "defined_as",
             "is_a", "has_a", "expands")

# Frame slots that become condition nodes, and the edge rel that
# attaches each one to the frame's action node.
_CONDITION_SLOTS = (
    ("when", "temporal"),
    ("where", "condition"),
    ("why", "condition"),
    ("how", "condition"),
)

# How many levels deep a definition expansion may go by default.
# Lexicon.decompose has its own cap; this one also guards callers
# that hand us a hand-built (possibly cyclic) decomposition tree.
DEFAULT_EXPANSION_DEPTH = 3


@dataclass
class ConceptNode:
    """One typed node in a concept graph."""

    id: str
    type: str                       # one of NODE_TYPES
    label: str
    attrs: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"id": self.id, "type": self.type, "label": self.label,
                "attrs": dict(self.attrs)}

    @classmethod
    def from_dict(cls, d: dict) -> "ConceptNode":
        return cls(id=d["id"], type=d["type"], label=d["label"],
                   attrs=dict(d.get("attrs") or {}))


@dataclass
class ConceptEdge:
    """One labelled, directed relation between two nodes."""

    source: str                     # node id
    target: str                     # node id
    rel: str                        # one of EDGE_RELS (or a frame rel)
    attrs: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"source": self.source, "target": self.target,
                "rel": self.rel, "attrs": dict(self.attrs)}

    @classmethod
    def from_dict(cls, d: dict) -> "ConceptEdge":
        return cls(source=d["source"], target=d["target"],
                   rel=d["rel"], attrs=dict(d.get("attrs") or {}))


class ConceptGraph:
    """An explicit graph of concepts, built from ConceptFrames.

    Nodes are deduplicated by (type, label): the same actor named in
    two frames is ONE node, so paths and contradiction checks join
    up across sentences. Edges are deduplicated by
    (source, target, rel). Node ids are stable within a graph and
    remapped on merge, so a merged graph never has id collisions.
    """

    def __init__(self, label: str | None = None):
        self.label = label
        self.nodes: dict[str, ConceptNode] = {}
        self.edges: list[ConceptEdge] = []
        self._next_id = 1
        self._node_key: dict[tuple[str, str], str] = {}
        self._edge_key: set[tuple[str, str, str]] = set()
        # Terms already expanded by expand_definition(), so a second
        # call for the same term is a no-op (cycle safety at the
        # graph level, on top of the lexicon's own visited set).
        self._expanded_terms: set[str] = set()

    # -- construction --------------------------------------------------
    def _new_id(self) -> str:
        nid = f"n{self._next_id}"
        self._next_id += 1
        return nid

    def add_node(self, type: str, label: str,
                 attrs: dict | None = None,
                 unique: bool = False) -> str:
        """Add (or reuse) a node; returns its id.

        Reuse is by (type, label): the same actor named in two
        frames is ONE node, so paths and contradiction checks join
        up across sentences. ``unique=True`` skips reuse: each
        frame gets its own action node (and its own relationship
        node), because two events with the same verb — e.g. "gave"
        vs "did not give" — are two distinct claims, and collapsing
        them would erase the very contradiction the graph must be
        able to report. Later attrs only fill keys the node does
        not already have, so a merge never silently overwrites an
        earlier fact.
        """
        if type not in NODE_TYPES:
            raise ValueError(f"unknown node type: {type!r}")
        key = (type, label)
        if not unique:
            existing = self._node_key.get(key)
            if existing is not None:
                node = self.nodes[existing]
                for k, v in (attrs or {}).items():
                    node.attrs.setdefault(k, v)
                return existing
        nid = self._new_id()
        self.nodes[nid] = ConceptNode(
            id=nid, type=type, label=label, attrs=dict(attrs or {}))
        self._node_key[key if not unique else (type, label, nid)] = nid
        return nid

    def add_edge(self, source: str, target: str, rel: str,
                 attrs: dict | None = None) -> bool:
        """Add an edge; returns False when it already exists."""
        if source not in self.nodes or target not in self.nodes:
            raise ValueError("edge endpoints must be nodes in the graph")
        key = (source, target, rel)
        if key in self._edge_key:
            return False
        self.edges.append(ConceptEdge(
            source=source, target=target, rel=rel,
            attrs=dict(attrs or {})))
        self._edge_key.add(key)
        return True

    def add_causation(self, cause_id: str, effect_id: str,
                      attrs: dict | None = None) -> bool:
        """Explicit causation edge. Only a caller that has evidence
        for a causal claim may add one — frames never imply it."""
        return self.add_edge(cause_id, effect_id, "causation",
                             attrs=attrs)

    def merge(self, other: "ConceptGraph") -> dict[str, str]:
        """Merge another graph in, remapping its ids. Returns the
        id map (other id -> this graph's id)."""
        id_map: dict[str, str] = {}
        for node in other.nodes.values():
            id_map[node.id] = self.add_node(
                node.type, node.label, attrs=node.attrs,
                unique=node.type in ("action", "relationship"))
        for edge in other.edges:
            self.add_edge(id_map[edge.source], id_map[edge.target],
                          edge.rel, attrs=edge.attrs)
        self._expanded_terms |= set(other._expanded_terms)
        return id_map

    # -- construction from frames --------------------------------------
    @classmethod
    def from_frames(cls, frames: list[ConceptFrame],
                    label: str | None = None) -> "ConceptGraph":
        """Build a graph from shared ConceptFrames.

        Per frame: ``who`` -> actor node, ``what`` -> action node,
        ``object`` -> object node, ``recipient`` -> actor node,
        ``when``/``where``/``why``/``how`` -> condition nodes,
        ``quantity`` -> a ``quantity`` edge action -> object,
        ``kind == "calculation"`` -> a consequence node holding the
        result. Frame ``relationships`` entries become
        ``relationship`` nodes attached to the action node. A negated
        frame marks the action node ``polarity: negative`` and adds
        ``polarity`` edges (action -> actor, action -> object).
        ``None`` slots produce nothing.
        """
        graph = cls(label=label)
        for i, frame in enumerate(frames):
            graph._add_frame(frame, frame_index=i)
        return graph

    def _add_frame(self, frame: ConceptFrame,
                   frame_index: int | None = None) -> str | None:
        """Add one frame; returns the action node's id (or None
        when the frame has no action to anchor on). The action node
        is unique per frame (see add_node): two frames with the same
        verb are two distinct events."""
        action_id = None
        if frame.what is not None:
            action_attrs: dict = {"kind": frame.kind,
                                  "polarity": frame.polarity,
                                  "certainty": frame.certainty,
                                  "source_text": frame.source_text}
            if frame_index is not None:
                action_attrs["frame_index"] = frame_index
            action_id = self.add_node(
                "action", frame.what, attrs=action_attrs, unique=True)
        actor_id = None
        if frame.who is not None:
            actor_id = self.add_node("actor", frame.who)
        object_id = None
        if frame.object is not None:
            object_attrs: dict = {}
            if frame.quantity is not None:
                object_attrs["quantity"] = frame.quantity
            if frame.units is not None:
                object_attrs["units"] = frame.units
            object_id = self.add_node("object", frame.object,
                                      attrs=object_attrs)
        recipient_id = None
        if frame.recipient is not None:
            recipient_id = self.add_node("actor", frame.recipient)
        if action_id is not None:
            if actor_id is not None:
                self.add_edge(actor_id, action_id, "agent")
            if object_id is not None:
                self.add_edge(action_id, object_id, "patient")
            if recipient_id is not None:
                self.add_edge(action_id, recipient_id, "recipient")
            if frame.quantity is not None and object_id is not None:
                self.add_edge(
                    action_id, object_id, "quantity",
                    attrs={"value": frame.quantity,
                           "units": frame.units})
            if frame.polarity == "negative":
                # Negation is an explicit edge, not a dropped flag:
                # the action is denied of its actor (and its object).
                if actor_id is not None:
                    self.add_edge(action_id, actor_id, "polarity",
                                  attrs={"value": "negative"})
                if object_id is not None:
                    self.add_edge(action_id, object_id, "polarity",
                                  attrs={"value": "negative"})
            for slot, rel in _CONDITION_SLOTS:
                value = getattr(frame, slot)
                if value is not None:
                    cond_id = self.add_node(
                        "condition", value, attrs={"slot": slot})
                    self.add_edge(action_id, cond_id, rel)
            for rel_entry in frame.relationships or []:
                rel = rel_entry.get("rel")
                target = rel_entry.get("target")
                if not rel or target is None:
                    continue
                rel_id = self.add_node(
                    "relationship", rel,
                    attrs={"target": target,
                           **{k: v for k, v in rel_entry.items()
                              if k not in ("rel", "target")}},
                    unique=True)
                self.add_edge(action_id, rel_id, rel)
        if frame.kind == "calculation" and frame.quantity is not None:
            result_label = (f"{frame.quantity} {frame.units}"
                            if frame.units else str(frame.quantity))
            cons_id = self.add_node(
                "consequence", result_label,
                attrs={"quantity": frame.quantity,
                       "units": frame.units,
                       "source_text": frame.source_text})
            if action_id is not None:
                self.add_edge(action_id, cons_id, "causation",
                              attrs={"derived": "calculation"})
        return action_id

    def add_frames(self, frames: list[ConceptFrame]) -> list[str | None]:
        """Add frames to an existing graph; returns action node ids."""
        base = len(self.actions())
        return [self._add_frame(f, frame_index=base + i)
                for i, f in enumerate(frames)]

    # -- definition expansion ------------------------------------------
    def expand_definition(self, term: str, lexicon,
                          depth: int = DEFAULT_EXPANSION_DEPTH
                          ) -> str | None:
        """Expand a defined term into its definition's graph.

        ``lexicon`` is any object with ``decompose(term, depth)``
        returning the ``Lexicon.decompose`` tree (``{"term",
        "gloss", "frames": [...], "components": [...]}``) or None
        for an unknown term. The term becomes an ``object`` node;
        each level's frames are added via ``from_frames`` and linked
        to the term node with ``defined_as`` edges; component terms
        are expanded one level deeper. Depth-limited and cycle-safe:
        a term already expanded in this graph (or already on the
        current expansion path) is never re-entered, and ``depth``
        bounds the recursion even for a hand-built cyclic tree.
        Returns the term node's id, or None when the term is
        unknown to the lexicon.
        """
        key = term.strip().lower()
        if not key:
            return None
        if key in self._expanded_terms:
            # Already expanded: return the existing term node.
            return self._node_key.get(("object", key))
        if depth < 1:
            return None
        tree = lexicon.decompose(term, depth=depth)
        if tree is None:
            return None
        self._expanded_terms.add(key)
        term_id = self.add_node(
            "object", tree.get("term", key),
            attrs={"gloss": tree.get("gloss"),
                   "source": tree.get("source"),
                   "defined_term": True})
        self._expand_tree(tree, term_id, depth=depth,
                          _path={key})
        return term_id

    def _expand_tree(self, tree: dict, term_id: str, depth: int,
                     _path: set) -> None:
        """Merge one decomposition tree into this graph.

        ``_path`` is the set of terms on the current expansion path
        (cycle guard for hand-built trees); ``depth`` is the levels
        remaining below this tree.
        """
        frames = []
        for f in tree.get("frames") or []:
            try:
                frames.append(ConceptFrame.from_dict(f)
                              if isinstance(f, dict) else f)
            except Exception:
                continue
        sub = ConceptGraph.from_frames(frames)
        id_map = self.merge(sub)
        # Link the defined term to the actions its definition states.
        # Action nodes are unique per frame, so link via the merged
        # sub-graph's own action nodes (not a (type, label) lookup).
        for sub_node in sub.nodes.values():
            if sub_node.type == "action":
                self.add_edge(term_id, id_map[sub_node.id],
                              "defined_as")
        if depth <= 1:
            return
        for child in tree.get("components") or []:
            child_key = str(child.get("term", "")).strip().lower()
            if not child_key or child_key in _path:
                continue
            child_id = self.add_node(
                "object", child.get("term", child_key),
                attrs={"gloss": child.get("gloss"),
                       "source": child.get("source"),
                       "defined_term": True})
            self.add_edge(term_id, child_id, "expands")
            self._expanded_terms.add(child_key)
            self._expand_tree(child, child_id, depth - 1,
                              _path | {child_key})

    # -- queries ---------------------------------------------------------
    def nodes_by_type(self, type: str) -> list[ConceptNode]:
        return [n for n in self.nodes.values() if n.type == type]

    def actors(self) -> list[ConceptNode]:
        return self.nodes_by_type("actor")

    def actions(self) -> list[ConceptNode]:
        return self.nodes_by_type("action")

    def objects(self) -> list[ConceptNode]:
        return self.nodes_by_type("object")

    def conditions(self) -> list[ConceptNode]:
        return self.nodes_by_type("condition")

    def relationships(self) -> list[ConceptNode]:
        return self.nodes_by_type("relationship")

    def consequences(self) -> list[ConceptNode]:
        return self.nodes_by_type("consequence")

    def find_nodes(self, label: str,
                   type: str | None = None) -> list[ConceptNode]:
        return [n for n in self.nodes.values()
                if n.label == label and (type is None or n.type == type)]

    def neighbors(self, node_id: str, rel: str | None = None,
                  direction: str = "out") -> list[ConceptNode]:
        """Neighbour nodes of ``node_id`` via edges (optionally
        filtered by ``rel``). ``direction`` is "out", "in", or
        "both"."""
        out: list[ConceptNode] = []
        seen: set[str] = set()
        for e in self.edges:
            other = None
            if direction in ("out", "both") and e.source == node_id:
                other = e.target
            elif direction in ("in", "both") and e.target == node_id:
                other = e.source
            if other is not None and other not in seen and \
                    (rel is None or e.rel == rel):
                seen.add(other)
                out.append(self.nodes[other])
        return out

    def edges_from(self, node_id: str,
                   rel: str | None = None) -> list[ConceptEdge]:
        return [e for e in self.edges
                if e.source == node_id and (rel is None or e.rel == rel)]

    def edges_to(self, node_id: str,
                 rel: str | None = None) -> list[ConceptEdge]:
        return [e for e in self.edges
                if e.target == node_id and (rel is None or e.rel == rel)]

    def path_between(self, start_id: str, end_id: str,
                     rel: str | None = None) -> list[str] | None:
        """Shortest directed path (BFS) from ``start_id`` to
        ``end_id`` as a list of node ids, or None when unreachable.
        ``rel`` restricts traversal to one relation type."""
        if start_id not in self.nodes or end_id not in self.nodes:
            return None
        if start_id == end_id:
            return [start_id]
        prev: dict[str, str | None] = {start_id: None}
        queue: deque[str] = deque([start_id])
        while queue:
            cur = queue.popleft()
            for edge in self.edges_from(cur, rel=rel):
                nxt = edge.target
                if nxt not in prev:
                    prev[nxt] = cur
                    if nxt == end_id:
                        path = [nxt]
                        while prev[path[-1]] is not None:
                            path.append(prev[path[-1]])  # type: ignore[arg-type]
                        return list(reversed(path))
                    queue.append(nxt)
        return None

    def subgraph_by_condition(self, condition_label: str
                              ) -> "ConceptGraph":
        """The subgraph around one condition node: the condition
        itself, every action attached to it, and those actions'
        actors, objects, recipients and other conditions — plus the
        edges between the kept nodes. An empty graph when the
        condition is absent (never a guessed subgraph)."""
        cond_ids = [n.id for n in self.conditions()
                    if n.label == condition_label]
        sub = ConceptGraph(label=f"condition:{condition_label}")
        if not cond_ids:
            return sub
        keep: set[str] = set(cond_ids)
        id_map: dict[str, str] = {}
        for cid in cond_ids:
            for action in self.neighbors(cid, direction="in"):
                keep.add(action.id)
                # Actors point INTO the action, objects/recipients/
                # conditions point OUT of it: take both directions.
                for nb in self.neighbors(action.id, direction="both"):
                    keep.add(nb.id)
        for nid in sorted(keep):
            node = self.nodes[nid]
            # Action/relationship nodes are unique per frame (see
            # add_node): preserve that here or two events collapse.
            new_id = sub.add_node(
                node.type, node.label, attrs=node.attrs,
                unique=node.type in ("action", "relationship"))
            id_map[nid] = new_id
        for edge in self.edges:
            if edge.source in keep and edge.target in keep:
                sub.add_edge(id_map[edge.source], id_map[edge.target],
                             edge.rel, attrs=edge.attrs)
        return sub

    def find_contradictions(self) -> list[dict]:
        """Contradiction support: pairs of action nodes that assert
        the same actor doing the same action to the same object
        with opposite polarity, or with conflicting quantities.

        Returns ``[{"type": "polarity"|"quantity", "actions":
        [id_a, id_b], "actor": ..., "action": ..., "object": ...,
        "detail": ...}]``. Same-polarity, same-quantity pairs are
        agreement, not contradiction, and are not reported.
        """
        def _slot(action_id: str, rel: str) -> str | None:
            # "agent" edges point INTO the action (actor -> action);
            # "patient"/"recipient" edges point OUT of it.
            if rel == "agent":
                incoming = [e.source for e in self.edges_to(action_id)
                            if e.rel == rel]
                if not incoming:
                    return None
                return self.nodes[incoming[0]].label
            targets = [e.target for e in self.edges_from(action_id)
                       if e.rel == rel]
            if not targets:
                return None
            return self.nodes[targets[0]].label

        def _quantity(action_id: str):
            for e in self.edges_from(action_id):
                if e.rel == "quantity":
                    return e.attrs.get("value")
            return None

        out: list[dict] = []
        actions = self.actions()
        for i, a in enumerate(actions):
            for b in actions[i + 1:]:
                actor_a, actor_b = _slot(a.id, "agent"), _slot(b.id, "agent")
                obj_a, obj_b = _slot(a.id, "patient"), _slot(b.id, "patient")
                if a.label != b.label or actor_a != actor_b \
                        or obj_a != obj_b:
                    continue
                pol_a = a.attrs.get("polarity", "positive")
                pol_b = b.attrs.get("polarity", "positive")
                if pol_a != pol_b:
                    out.append({
                        "type": "polarity", "actions": [a.id, b.id],
                        "actor": actor_a, "action": a.label,
                        "object": obj_a,
                        "detail": f"{actor_a} {a.label} {obj_a or ''} "
                                  f"asserted {pol_a} and {pol_b}".strip()})
                    continue
                q_a, q_b = _quantity(a.id), _quantity(b.id)
                if q_a is not None and q_b is not None and q_a != q_b:
                    out.append({
                        "type": "quantity", "actions": [a.id, b.id],
                        "actor": actor_a, "action": a.label,
                        "object": obj_a,
                        "detail": f"{actor_a} {a.label} {obj_a or ''}: "
                                  f"quantity {q_a} vs {q_b}".strip()})
        return out

    # -- serialization ---------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "edges": [e.to_dict() for e in self.edges],
            "expanded_terms": sorted(self._expanded_terms),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ConceptGraph":
        graph = cls(label=d.get("label"))
        for nd in d.get("nodes") or []:
            node = ConceptNode.from_dict(nd)
            graph.nodes[node.id] = node
            if node.type in ("action", "relationship"):
                graph._node_key[(node.type, node.label, node.id)] = node.id
            else:
                graph._node_key[(node.type, node.label)] = node.id
            try:
                num = int(node.id[1:])
                graph._next_id = max(graph._next_id, num + 1)
            except (ValueError, IndexError):
                pass
        for ed in d.get("edges") or []:
            edge = ConceptEdge.from_dict(ed)
            graph.edges.append(edge)
            graph._edge_key.add((edge.source, edge.target, edge.rel))
        graph._expanded_terms = set(d.get("expanded_terms") or [])
        return graph

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> "ConceptGraph":
        return cls.from_dict(json.loads(text))

    # -- dunder ------------------------------------------------------------
    def __len__(self) -> int:
        return len(self.nodes)

    def __contains__(self, node_id: str) -> bool:
        return node_id in self.nodes

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (f"ConceptGraph(label={self.label!r}, "
                f"nodes={len(self.nodes)}, edges={len(self.edges)})")
