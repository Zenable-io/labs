"""Copyright (c) 2026 Zenable, Inc. The level sets a Score is graded against, and where they land on 0 to 10.

Both readings share one anchor tuple and differ only in what their levels
describe. They sit in one short file because the wording is the policy: a
reviewer who wants to know what a 5 means reads this, and an edit here changes
every score the rubric produces.
"""

ANCHORS: tuple[float, ...] = (0.0, 3.0, 5.0, 8.0, 10.0)
"""Where each level sits on the 0 to 10 scale a threshold is written against."""

QUALITY_LEVELS: tuple[str, ...] = (
    "Absent. The subject shows nothing of this dimension.",
    "Weak. Traces of it, not enough for a reviewer to rely on.",
    "Adequate. Present and usable, with gaps a reviewer would note.",
    "Strong. Clearly present, and a reviewer would need no clarification.",
    "Exemplary. The best form of this a reviewer could reasonably see.",
)

RISK_LEVELS: tuple[str, ...] = (
    "None. Nothing here would concern a reviewer.",
    "Low. A reviewer would mention it and move on.",
    "Moderate. A reviewer would ask for a change before approving.",
    "High. A reviewer would block the change on it.",
    "Severe. The most serious form of this a reviewer could see.",
)

READINGS: dict[str, tuple[str, tuple[str, ...]]] = {
    "quality": (
        "Higher levels describe a better subject. Choose the level whose "
        "description the subject matches.",
        QUALITY_LEVELS,
    ),
    "risk": (
        "Higher levels describe more concern for a reviewer. Choose the level "
        "whose description the subject matches.",
        RISK_LEVELS,
    ),
}


def rubric_score(probabilities: dict[int, float]) -> float:
    """The level probabilities re-weighted over the anchors.

    `score` off the wire is a position on the level number line, so a threshold
    written against a 0 to 10 scale has to re-weight it. Reading `score`
    directly is an off-by-scale bug that every type check accepts.
    """
    return sum(ANCHORS[level] * weight for level, weight in probabilities.items())
