"""NOVA semantic layer: one universal cognitive language.

Every module reads and writes ConceptFrame (``frame.py``). The pipeline
(``pipeline.py``) is the single entry point: natural language in,
frames out, reasoning over frames, natural language back out.
"""

from .compare import compare_concept_frames, compare_texts
from .confidence import (CERTIFICATION_BAR, calibration_buckets,
                         model_agreement_factor, parse_certainty,
                         proof_completeness, score as confidence_score)
from .extract import find_query, parse_sentence_to_frame, parse_text_to_frames
from .facts import (extract_copula_question, extract_fact_frame,
                    extract_has_question, extract_per_unit_question,
                    find_per_unit_fact)
from .frame import ConceptFrame, normalize_person
from .interpret import (deterministic_simplifications, interpret,
                        model_simplifications, render_interpretation)
from .memory import FrameMemory
from .pipeline import answer_text, process_request
from .reason import SupervisoryReasoner
from .render import (render_amount_paid_answer, render_analysis,
                     render_balance_answer, render_per_unit_answer,
                     render_verdict_answer)
from .roundtrip import roundtrip_loss, roundtrip_sentence
from .router import route_sentence
from .translate import (balance_query_to_frame, frame_to_balance_query,
                        frame_to_fact, frame_to_transfer,
                        frames_to_facts, goal_frame_to_fact,
                        knowledge_hit_to_frame, list_knowledge_entries,
                        split_story_frames, transfer_to_frame)

__all__ = [
    "ConceptFrame", "SupervisoryReasoner", "FrameMemory",
    "answer_text", "process_request",
    "parse_text_to_frames", "parse_sentence_to_frame", "find_query",
    "compare_concept_frames", "compare_texts",
    "interpret", "deterministic_simplifications",
    "model_simplifications", "render_interpretation",
    "build_explanation_package", "build_variant_prompt",
    "coherence_scores", "ANSWER_INSTRUCTION", "VARIANTS",
    "build_explanation_package", "build_variant_prompt",
    "coherence_scores", "ANSWER_INSTRUCTION", "VARIANTS",
    "confidence_score", "parse_certainty", "proof_completeness",
    "model_agreement_factor", "calibration_buckets",
    "CERTIFICATION_BAR",
    "render_analysis", "render_balance_answer", "render_verdict_answer",
    "render_per_unit_answer", "render_amount_paid_answer",
    "transfer_to_frame", "balance_query_to_frame",
    "frame_to_transfer", "frame_to_balance_query",
    "frame_to_fact", "frames_to_facts", "goal_frame_to_fact",
    "knowledge_hit_to_frame", "list_knowledge_entries",
    "split_story_frames", "normalize_person",
    "route_sentence", "roundtrip_loss", "roundtrip_sentence",
    "extract_fact_frame", "extract_copula_question",
    "extract_has_question", "extract_per_unit_question",
    "find_per_unit_fact",
]
