"""Concept memory: a frame store.

The "memory" module of the architecture, speaking the same ConceptFrame
format as everything else: frames in, frames out. In-memory for now (the
HTTP API is stateless per request); this store is the seam a persistent
memory would plug into without changing the frame format or any caller.
"""

from __future__ import annotations

from .extract import normalize_person
from .frame import ConceptFrame


class FrameMemory:
    """Frames in, frames out, same format."""

    def __init__(self):
        self._frames: list[ConceptFrame] = []

    def remember(self, frame: ConceptFrame) -> None:
        self._frames.append(frame)

    def remember_all(self, frames: list[ConceptFrame]) -> None:
        self._frames.extend(frames)

    def recall(self, who: str | None = None, what: str | None = None,
               kind: str | None = None) -> list[ConceptFrame]:
        out = []
        for f in self._frames:
            if who is not None and normalize_person(f.who) != normalize_person(who):
                continue
            if what is not None and f.what != what:
                continue
            if kind is not None and f.kind != kind:
                continue
            out.append(f)
        return out

    def all(self) -> list[ConceptFrame]:
        return list(self._frames)

    def __len__(self) -> int:
        return len(self._frames)
