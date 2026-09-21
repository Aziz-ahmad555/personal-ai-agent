"""Base resume: applying only accepted changes, Markdown rendering, and the staleness stamp."""

from types import SimpleNamespace

from app.career.resume_base import (
    EducationItem,
    ExperienceItem,
    ResumeBase,
    SkillItem,
    apply_accepted,
    render_markdown,
)


def _base() -> ResumeBase:
    return ResumeBase(
        name="Aziz Ahmad",
        headline="ML/AI Engineer",
        location="Lahore",
        summary="Engineer who builds ML systems.",
        experiences=[
            ExperienceItem(
                "e1", "Old Co", "Intern", None, "2024-06-01", "2024-09-01", "Did data work."
            ),
            ExperienceItem(
                "e2", "New Co", "Engineer", "Remote", "2026-03-01", None, "Builds APIs."
            ),
        ],
        educations=[EducationItem("d1", "Iqra University", "BS", "Computer Science", None, None)],
        skills=[
            SkillItem("Linux", "advanced", None),
            SkillItem("Python", "expert", None),
            SkillItem("Docker", "advanced", None),
        ],
    )


def _change(change_type: str, target: str, after: str, decision: str):  # type: ignore[no-untyped-def]
    return SimpleNamespace(
        change_type=change_type, target_id=target, after_text=after, decision=decision
    )


def test_only_accepted_changes_take_effect() -> None:
    changes = [
        _change("rewrite", "summary", "Accepted summary.", "accepted"),
        _change("rewrite", "exp:e2", "Rejected wording.", "rejected"),
        _change("rewrite", "exp:e1", "Pending wording.", "pending"),
    ]

    result = apply_accepted(_base(), changes)

    assert result.summary == "Accepted summary."
    descriptions = {e.id: e.description for e in result.experiences}
    assert descriptions == {"e1": "Did data work.", "e2": "Builds APIs."}  # untouched


def test_applying_changes_never_mutates_the_original_base() -> None:
    base = _base()

    apply_accepted(base, [_change("rewrite", "summary", "Changed.", "accepted")])

    assert base.summary == "Engineer who builds ML systems."


def test_an_accepted_skills_order_reorders_without_adding_or_dropping() -> None:
    change = _change("skills_order", "skills", "Python\nDocker\nLinux", "accepted")

    result = apply_accepted(_base(), [change])

    assert [s.name for s in result.skills] == ["Python", "Docker", "Linux"]


def test_a_skills_order_naming_an_unknown_skill_cannot_add_it() -> None:
    change = _change("skills_order", "skills", "Kubernetes\nPython", "accepted")

    result = apply_accepted(_base(), [change])

    assert [s.name for s in result.skills] == ["Python", "Linux", "Docker"]  # Kubernetes ignored


def test_markdown_lists_newest_role_first_and_marks_current_work() -> None:
    markdown = render_markdown(_base())

    assert markdown.startswith("# Aziz Ahmad\nML/AI Engineer\nLahore\n")
    assert markdown.index("Engineer — New Co") < markdown.index("Intern — Old Co")
    assert "Mar 2026 – Present · Remote" in markdown
    assert "Jun 2024 – Sep 2024" in markdown
    assert "### Iqra University — BS, Computer Science" in markdown
    assert markdown.rstrip().endswith("Linux, Python, Docker")


def test_markdown_invents_no_contact_details_and_skips_empty_sections() -> None:
    bare = ResumeBase(name=None, headline="ML Engineer", location=None, summary=None)

    markdown = render_markdown(bare)

    assert markdown == "# ML Engineer\n"
    assert "@" not in render_markdown(_base())


def test_stamp_is_stable_and_changes_with_any_content_change() -> None:
    assert _base().stamp() == _base().stamp()

    edited = _base()
    edited.experiences[0].description = "Did different data work."

    assert edited.stamp() != _base().stamp()


def test_base_survives_a_json_round_trip() -> None:
    base = _base()

    assert ResumeBase.from_json(base.to_json()) == base
