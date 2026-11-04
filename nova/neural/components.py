"""Optional FLAN-T5 component: load a checkpoint behind the model
interface (stdlib + lazy imports only).

``FlanT5Component`` wraps one fixture directory. ``load()`` imports
``torch`` and ``transformers`` lazily — inside the method, not at
module import — so the import of this module can never break the
deterministic path. In this environment the imports fail (neither
package is installed, and no pip installs are allowed), so ``load()``
raises ``NeuralUnavailable`` naming the missing module, and
``generate()`` without a loaded model raises the same. That is the
designed behaviour: a fixture that cannot load reports exactly why
instead of faking a connection.

When the runtime is present, ``load()`` builds a
``T5ForConditionalGeneration`` + ``AutoTokenizer`` from the fixture
directory and ``generate()`` runs greedy decoding (temperature 0,
matching the checkpoints' training-time evaluation). ``complete()``
adapts it to the ``LanguageModel`` protocol so a loaded checkpoint
can serve as NOVA's model through ``nova.model_interface``.
"""

from __future__ import annotations

from pathlib import Path

from ..model_interface import ModelResponse
from .fixtures import FIXTURES, NeuralUnavailable, availability


class FlanT5Component:
    """One trained FLAN-T5-small checkpoint, loaded on demand."""

    def __init__(self, name: str, root: str | Path | None = None):
        if name not in FIXTURES:
            raise ValueError(f"unknown neural fixture '{name}' "
                             f"(known: {', '.join(FIXTURES)})")
        from .fixtures import locate_fixtures
        self.name = name
        self.directory = locate_fixtures(root)[name]
        self.model_id = f"flan-t5-small-{name}"
        self._model = None
        self._tokenizer = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def _missing_modules(self) -> list[str]:
        info = availability()
        return info["missing_modules"]

    def load(self) -> "FlanT5Component":
        """Load the checkpoint. Raises NeuralUnavailable with the
        exact blocker when the runtime or the files are absent. The
        weights are opened read-only; loading never modifies them."""
        missing = self._missing_modules()
        if missing:
            raise NeuralUnavailable(
                self.name,
                "cannot load: missing runtime modules: " +
                ", ".join(missing) +
                " (torch/transformers/sentencepiece are not installed)")
        import torch  # noqa: F401 - lazy; only when actually loading
        from transformers import (AutoTokenizer,
                                  T5ForConditionalGeneration)
        self._tokenizer = AutoTokenizer.from_pretrained(
            str(self.directory))
        self._model = T5ForConditionalGeneration.from_pretrained(
            str(self.directory), torch_dtype=torch.float32)
        self._model.eval()
        return self

    def generate(self, prompt: str, max_new_tokens: int = 64) -> str:
        """Greedy generation. Raises NeuralUnavailable when not
        loaded — it never returns a fabricated completion."""
        if not self.loaded:
            raise NeuralUnavailable(
                self.name,
                "generate() called before load(); the checkpoint is "
                "not loaded in this environment")
        import torch
        enc = self._tokenizer([prompt], return_tensors="pt")
        with torch.no_grad():
            out = self._model.generate(
                **enc, max_new_tokens=max_new_tokens, do_sample=False)
        return self._tokenizer.decode(out[0], skip_special_tokens=True)

    def complete(self, prompt: str, *, max_tokens: int = 128,
                 temperature: float = 0.0) -> ModelResponse:
        """The LanguageModel protocol, backed by this checkpoint."""
        text = self.generate(prompt, max_new_tokens=max_tokens)
        return ModelResponse(text=text, model_id=self.model_id)


def component_status(root: str | Path | None = None) -> dict:
    """Status of every fixture component: present, loadable, and the
    blocker when it is not. Thin wrapper over ``fixture_status``."""
    from .fixtures import fixture_status, locate_fixtures
    status = fixture_status(root)
    dirs = locate_fixtures(root)
    status["components"] = {
        name: {"directory": str(directory), "loaded": False}
        for name, directory in dirs.items()}
    return status
