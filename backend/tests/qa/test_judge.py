from evaluation.qa.judge import Grade, grade_summary


def test_critical_failure_overrides_high_score() -> None:
    grade = Grade(
        findings=6,
        citations=2,
        caveats=1,
        interpretation=1,
        critical_failures=["Invented AI ROI"],
        missing_findings=[],
        incorrect_claims=["ROI is 30%"],
        explanation="Unsupported causal claim",
    )
    result = grade_summary(grade)
    assert result["score"] == 10
    assert not result["rubric_pass"]
    assert result["human_review_required"]
