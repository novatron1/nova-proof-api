"""Fixture locations, configs, and availability (stdlib only).

The checkpoint paths live under the ARC paper-track goal workspace.
``NOVA_NEURAL_ROOT`` may override the base directory; the default is
the recorded location. Nothing here imports torch or transformers —
availability is probed with ``importlib`` so the check itself can
never crash the deterministic path.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

DEFAULT_ROOT = Path.home() / "workspace" / "goals" / \
    "arc-prize-2026-paper-track-entry"

# name -> (relative dir, role, recorded result)
FIXTURES = {
    "learned_reasoner": (
        "push1-learned-reasoner/runs/reasoner-fast",
        "rule+fact JSON prompt -> Yes/No",
        "2000/2000 on novel-word test (test_novel.jsonl.gz)",
    ),
    "neural_parser": (
        "push2-template10-fix/models/p2-augH/checkpoint-500",
        "raw sentence -> JSON frame {kind, head, body, subject}",
        "COLLAPSED on held-out cell (0.2872) — fixture only",
    ),
}

# Files every fixture must have to count as present.
REQUIRED_FILES = ("config.json", "generation_config.json",
                  "tokenizer.json", "tokenizer_config.json",
                  "model.safetensors")

# The runtime the checkpoints need to actually load.
REQUIRED_MODULES = ("torch", "transformers", "sentencepiece")


class NeuralUnavailable(Exception):
    """A neural fixture cannot be used in this environment.

    ``reason`` names the exact blocker (missing file, missing module)
    so the failure is diagnosable, not a silent degradation.
    """

    def __init__(self, fixture: str, reason: str):
        super().__init__(f"{fixture}: {reason}")
        self.fixture = fixture
        self.reason = reason


def locate_fixtures(root: str | os.PathLike | None = None) -> dict:
    """Resolve each fixture's directory under ``root`` (default:
    ``$NOVA_NEURAL_ROOT`` or the recorded workspace path)."""
    base = Path(root or os.getenv("NOVA_NEURAL_ROOT") or DEFAULT_ROOT)
    return {name: base / rel for name, (rel, _r, _n) in FIXTURES.items()}


def _read_config(directory: Path) -> dict | None:
    try:
        return json.loads((directory / "config.json").read_text())
    except (OSError, ValueError):
        return None


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def availability(root: str | os.PathLike | None = None) -> dict:
    """Per-fixture availability: files present, config parsed, and
    which runtime modules are missing. Pure inspection — no imports
    of torch/transformers, no model loading."""
    dirs = locate_fixtures(root)
    missing_modules = [m for m in REQUIRED_MODULES
                       if not _module_available(m)]
    out = {"missing_modules": missing_modules,
           "loadable": not missing_modules, "fixtures": {}}
    for name, directory in dirs.items():
        present = {f: (directory / f).exists() for f in REQUIRED_FILES}
        config = _read_config(directory)
        weights = directory / "model.safetensors"
        out["fixtures"][name] = {
            "directory": str(directory),
            "present": all(present.values()),
            "missing_files": [f for f, ok in present.items() if not ok],
            "weights_bytes": (weights.stat().st_size
                              if weights.exists() else None),
            "architecture": (config or {}).get("architectures"),
            "model_type": (config or {}).get("model_type"),
            "d_model": (config or {}).get("d_model"),
            "num_layers": (config or {}).get("num_layers"),
            "vocab_size": (config or {}).get("vocab_size"),
            "role": FIXTURES[name][1],
            "recorded_result": FIXTURES[name][2],
        }
    return out


def fixture_status(root: str | os.PathLike | None = None) -> dict:
    """One status dict for the whole neural layer: which fixtures are
    present, whether anything can load, and the exact blocker when
    it cannot. Safe to call from anywhere, including the API."""
    info = availability(root)
    blockers = []
    if info["missing_modules"]:
        blockers.append(
            "missing runtime modules: " +
            ", ".join(info["missing_modules"]) +
            " (no pip installs allowed in this task)")
    for name, f in info["fixtures"].items():
        if not f["present"]:
            blockers.append(
                f"{name}: missing files: " +
                ", ".join(f["missing_files"]))
    return {
        "loadable": info["loadable"] and all(
            f["present"] for f in info["fixtures"].values()),
        "missing_modules": info["missing_modules"],
        "blockers": blockers,
        "fixtures": info["fixtures"],
    }
