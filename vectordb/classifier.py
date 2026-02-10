"""Rule-based content type classification for Forge OS Layer 1: MEMORY."""

import re

from vectordb.config import (
    CONTENT_TYPE_CODE_PATTERN,
    CONTENT_TYPE_CONVERSATION,
    CONTENT_TYPE_DECISION,
    CONTENT_TYPE_ERROR_RECOVERY,
    CONTENT_TYPE_OPTIMIZATION,
    CONTENT_TYPE_ROUTING,
    CONTENT_TYPE_SOLUTION,
)

# Each rule: (content_type, list_of_regex_patterns, min_matches)
# A text must match >= min_matches patterns to qualify for that type.
_CLASSIFICATION_RULES = (
    (
        CONTENT_TYPE_CODE_PATTERN,
        (
            re.compile(r"```[\s\S]*?```", re.MULTILINE),
            re.compile(r"\bdef\s+\w+", re.IGNORECASE),
            re.compile(r"\bfunction\s+\w+", re.IGNORECASE),
            re.compile(r"\bclass\s+\w+", re.IGNORECASE),
            re.compile(r"\bimport\s+\w+", re.IGNORECASE),
            re.compile(r"\bconst\s+\w+\s*=", re.IGNORECASE),
            re.compile(r"\blet\s+\w+\s*=", re.IGNORECASE),
            re.compile(r"\breturn\s+", re.IGNORECASE),
        ),
        2,
    ),
    (
        CONTENT_TYPE_ERROR_RECOVERY,
        (
            re.compile(r"\berror\b", re.IGNORECASE),
            re.compile(r"\bexception\b", re.IGNORECASE),
            re.compile(r"\btraceback\b", re.IGNORECASE),
            re.compile(r"\bfix(ed|ing)?\b", re.IGNORECASE),
            re.compile(r"\bdebug(ging)?\b", re.IGNORECASE),
            re.compile(r"\bsolved\b", re.IGNORECASE),
            re.compile(r"\bbug\b", re.IGNORECASE),
            re.compile(r"\bcrash(ed|ing)?\b", re.IGNORECASE),
        ),
        2,
    ),
    (
        CONTENT_TYPE_DECISION,
        (
            re.compile(r"\bdecide[ds]?\b", re.IGNORECASE),
            re.compile(r"\btrade-?off", re.IGNORECASE),
            re.compile(r"\bpros?\s+and\s+cons?\b", re.IGNORECASE),
            re.compile(r"\boption\s+[A-D]\b", re.IGNORECASE),
            re.compile(r"\brecommend(ation|ed)?\b", re.IGNORECASE),
            re.compile(r"\bchoose\b|\bchose\b|\bchoice\b", re.IGNORECASE),
            re.compile(r"\bcompar(e|ing|ison)\b", re.IGNORECASE),
        ),
        2,
    ),
    (
        CONTENT_TYPE_SOLUTION,
        (
            re.compile(r"\bsolution\b", re.IGNORECASE),
            re.compile(r"\bimplement(ation|ed|ing)?\b", re.IGNORECASE),
            re.compile(r"\bbuild(ing)?\b", re.IGNORECASE),
            re.compile(r"\barchitecture\b", re.IGNORECASE),
            re.compile(r"\bpipeline\b", re.IGNORECASE),
            re.compile(r"\bdesign(ed|ing)?\b", re.IGNORECASE),
            re.compile(r"\bsystem\b", re.IGNORECASE),
        ),
        2,
    ),
    (
        CONTENT_TYPE_OPTIMIZATION,
        (
            re.compile(r"\bperformance\b", re.IGNORECASE),
            re.compile(r"\boptimiz(e|ation|ed|ing)\b", re.IGNORECASE),
            re.compile(r"\bcache[ds]?\b", re.IGNORECASE),
            re.compile(r"\blatency\b", re.IGNORECASE),
            re.compile(r"\bbenchmark\b", re.IGNORECASE),
            re.compile(r"\bspeed\b|\bfaster\b|\bslower\b", re.IGNORECASE),
            re.compile(r"\bthroughput\b", re.IGNORECASE),
        ),
        2,
    ),
    (
        CONTENT_TYPE_ROUTING,
        (
            re.compile(r"\bAPI\b"),
            re.compile(r"\bendpoint\b", re.IGNORECASE),
            re.compile(r"\broute[ds]?\b", re.IGNORECASE),
            re.compile(r"\bmiddleware\b", re.IGNORECASE),
            re.compile(r"\bREST\b"),
            re.compile(r"\bGraphQL\b", re.IGNORECASE),
            re.compile(r"\bHTTP\b", re.IGNORECASE),
            re.compile(r"\bwebhook\b", re.IGNORECASE),
        ),
        2,
    ),
)


def classify_content(text):
    """Classify text into a content type using rule-based regex matching.

    Returns the first content type that matches >= min_matches patterns,
    evaluated in priority order. Falls back to 'conversation' if no rules match.
    """
    if not text:
        return CONTENT_TYPE_CONVERSATION

    for content_type, patterns, min_matches in _CLASSIFICATION_RULES:
        match_count = sum(1 for p in patterns if p.search(text))
        if match_count >= min_matches:
            return content_type

    return CONTENT_TYPE_CONVERSATION
