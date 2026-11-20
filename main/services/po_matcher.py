import re

from django.db import transaction
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from main.models import LOToPO, ProgramOutcome


STANDARD_PO_CODES = tuple(f"PO{number}" for number in range(1, 12))
MAX_MATCHED_POS = 2

HEURISTIC_KEYWORDS = {
    "PO1": (
        "math", "mathematics", "calculus", "physics", "theory", "model",
        "concept", "foundation", "scientific", "computation",
    ),
    "PO2": (
        "algorithm", "analyz", "evaluat", "assess", "identif", "select",
        "perform", "compar", "solv", "formulat", "problem",
    ),
    "PO3": (
        "implement", "design", "develop", "pipelin", "architect", "build",
        "cod", "program", "system", "deploy", "prototype", "construct",
    ),
    "PO4": (
        "experiment", "investigat", "data", "machin learn", "dataset",
        "metric", "validat", "test", "measure", "research",
    ),
    "PO5": (
        "tool", "librar", "framework", "softwar", "python", "technolog",
        "comput", "information technology",
    ),
    "PO6": ("team", "collaborate", "individual", "interdisciplinary"),
    "PO7": ("communicate", "presentation", "report", "written", "oral"),
    "PO8": ("lifelong learning", "self-learning", "independent learning"),
    "PO9": ("ethics", "ethical", "professional", "moral", "responsibility"),
    "PO10": (
        "project management",
        "management",
        "cost",
        "economics",
        "entrepreneurship",
    ),
    "PO11": ("health", "environment", "safety", "legal", "law"),
}


def _keyword_boost(text, keywords):
    tokens = re.findall(r"[a-z0-9]+", text.casefold())
    boost_count = 0
    for keyword in keywords:
        keyword_tokens = re.findall(r"[a-z0-9]+", keyword.casefold())
        if not keyword_tokens:
            continue
        token_count = len(keyword_tokens)
        if any(
            all(
                text_token.startswith(keyword_token)
                for text_token, keyword_token in zip(
                    tokens[index:index + token_count],
                    keyword_tokens,
                )
            )
            for index in range(len(tokens) - token_count + 1)
        ):
            boost_count += 1
    return 0.2 * boost_count


def map_course_los_to_pos(course):
    """Map each course learning outcome to relevant POs using TF-IDF and keywords."""
    learning_outcomes = list(course.learning_outcomes.order_by("code", "pk"))
    if not learning_outcomes:
        return {}

    outcomes_by_code = ProgramOutcome.objects.in_bulk(
        STANDARD_PO_CODES,
        field_name="code",
    )
    program_outcomes = [
        outcomes_by_code[code]
        for code in STANDARD_PO_CODES
        if code in outcomes_by_code
    ]
    if not program_outcomes:
        return {learning_outcome.pk: [] for learning_outcome in learning_outcomes}

    po_descriptions = [
        f"{outcome.title} {outcome.description}".strip()
        for outcome in program_outcomes
    ]
    lo_descriptions = [outcome.description.strip() for outcome in learning_outcomes]
    documents = po_descriptions + lo_descriptions
    try:
        vectors = TfidfVectorizer(
            stop_words="english",
            ngram_range=(1, 2),
        ).fit_transform(documents)
        similarities = cosine_similarity(
            vectors[len(program_outcomes) :],
            vectors[: len(program_outcomes)],
        )
    except ValueError as exc:
        if "empty vocabulary" not in str(exc):
            raise
        similarities = [[0.0] * len(program_outcomes) for _ in learning_outcomes]

    mapping_results = {}
    with transaction.atomic():
        for lo_index, learning_outcome in enumerate(learning_outcomes):
            description = lo_descriptions[lo_index]
            scores = []
            for po_index, program_outcome in enumerate(program_outcomes):
                score = float(similarities[lo_index][po_index])
                score += _keyword_boost(
                    description,
                    HEURISTIC_KEYWORDS.get(program_outcome.code, ()),
                )
                if score > 0:
                    scores.append((program_outcome, score))

            scores.sort(key=lambda item: (-item[1], item[0].code))
            scores = scores[:MAX_MATCHED_POS]
            if not scores:
                technical_outcomes = [
                    outcomes_by_code[code]
                    for code in ("PO1", "PO2", "PO3")
                    if code in outcomes_by_code
                ]
                fallback_outcomes = technical_outcomes or program_outcomes[:3]
                scores = [
                    (program_outcome, 1.0)
                    for program_outcome in fallback_outcomes
                ]

            total_score = sum(score for _, score in scores)
            normalized_scores = [
                (program_outcome, score * 100.0 / total_score)
                for program_outcome, score in scores
            ]
            LOToPO.objects.filter(learning_outcome=learning_outcome).delete()
            LOToPO.objects.bulk_create(
                [
                    LOToPO(
                        learning_outcome=learning_outcome,
                        program_outcome=program_outcome,
                        weight=weight,
                    )
                    for program_outcome, weight in normalized_scores
                ]
            )
            mapping_results[learning_outcome.pk] = [
                {
                    "program_outcome": program_outcome,
                    "weight": weight,
                }
                for program_outcome, weight in normalized_scores
            ]

    return mapping_results
