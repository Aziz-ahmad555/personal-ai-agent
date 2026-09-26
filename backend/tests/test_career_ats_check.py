"""ATS checks and the ATS-safe rendering — pure functions, no DB. The keyword states, each
structural check, and the guarantee that the ATS-safe text really is free of the hazards."""

import pytest

from app.career.ats_check import (
    check_keywords,
    check_structure,
    split_sections,
    summarize,
)
from app.career.ats_render import (
    find_hazard_chars,
    markdown_marker_count,
    render_ats_plain,
    to_ascii_safe,
)
from app.career.resume_base import (
    EducationItem,
    ExperienceItem,
    ResumeBase,
    SkillItem,
    render_markdown,
)


def _base(**overrides) -> ResumeBase:  # type: ignore[no-untyped-def]
    params = {
        "name": "Aziz Ahmad",
        "headline": "ML/AI Engineer",
        "location": "Lahore",
        "summary": "Engineer who builds machine learning systems and APIs.",
        "experiences": [
            ExperienceItem(
                "e1",
                "University",
                "Vaultic",
                None,
                "2026-03-01",
                None,
                "Built a fraud detection application using Flask and PostgreSQL.",
                ["Flask", "FastAPI"],
            ),
            ExperienceItem(
                "e2",
                "Individual",
                "AegisAI",
                "Remote",
                "2025-01-01",
                "2025-12-01",
                "Built a real-time vision platform.",
                [],
            ),
        ],
        "educations": [
            EducationItem("d1", "Iqra University", "BS", "Computer Science", "2022-09-01", None)
        ],
        "skills": [
            SkillItem("Flask", "advanced", None, "e"),
            SkillItem("FastAPI", "advanced", None, "e"),
            SkillItem("PostgreSQL", "advanced", None, "e"),
        ],
        "unevidenced_skills": ["Docker"],
        **overrides,
    }
    return ResumeBase(**params)


def _req(name: str, kind: str = "required") -> dict[str, str]:
    return {"name": name, "kind": kind, "quote": name}


def _states(text: str, base: ResumeBase, *names: str) -> dict[str, str]:
    results, _ = check_keywords(text, [_req(n) for n in names], base)
    return {r.name: r.state for r in results}


def test_a_skill_used_in_a_role_is_in_context() -> None:
    base = _base()

    assert _states(render_markdown(base), base, "Flask") == {"Flask": "in_context"}


def test_a_skill_only_in_the_skills_list_is_listed_only_and_points_at_its_roles() -> None:
    base = _base()

    results, _ = check_keywords(render_markdown(base), [_req("FastAPI")], base)

    assert results[0].state == "listed_only"
    assert results[0].roles == ["Vaultic — University"]  # where its evidence says it was used
    assert "Vaultic — University" in results[0].detail


def test_a_skill_that_is_not_on_the_resume_is_a_gap_with_the_right_reason() -> None:
    base = _base()
    results, _ = check_keywords(render_markdown(base), [_req("Docker"), _req("Kubernetes")], base)
    reasons = {r.name: r.detail for r in results}

    assert all(r.state == "gap" for r in results)
    assert "no evidence recorded" in reasons["Docker"]
    assert "isn't in your profile" in reasons["Kubernetes"]


def test_a_gap_is_never_suggested_for_insertion() -> None:
    base = _base()

    results, _ = check_keywords(render_markdown(base), [_req("Kubernetes")], base)

    assert results[0].roles == []
    assert "add" not in results[0].detail.lower()


def test_skill_aliases_count_as_the_same_skill() -> None:
    base = _base()

    assert _states(render_markdown(base), base, "Postgres") == {"Postgres": "in_context"}


def test_coverage_stats_and_deduplication() -> None:
    base = _base()
    requirements = [
        _req("Flask"),
        _req("FastAPI"),
        _req("Kubernetes"),
        _req("flask"),  # duplicate of Flask once normalized
        _req("Docker", "preferred"),
    ]

    results, stats = check_keywords(render_markdown(base), requirements, base)

    assert [r.name for r in results] == ["Flask", "FastAPI", "Kubernetes", "Docker"]
    assert (stats.required_found, stats.required_total) == (2, 3)
    assert (stats.preferred_found, stats.preferred_total) == (0, 1)
    assert stats.in_context == 1
    assert stats.coverage_percent == 50  # 2 of 4 found anywhere


def test_no_requested_skills_means_no_coverage_number_not_a_fake_one() -> None:
    _, stats = check_keywords(render_markdown(_base()), [], _base())

    assert stats.coverage_percent is None
    assert (stats.required_total, stats.preferred_total) == (0, 0)


def test_text_with_no_headings_counts_any_mention_as_in_context() -> None:
    assert _states("I build things with Flask.", _base(), "Flask") == {"Flask": "in_context"}


def test_section_splitting_understands_markdown_and_plain_headings() -> None:
    markdown = split_sections(render_markdown(_base()))
    plain = split_sections(render_ats_plain(_base()))

    assert [s.key for s in markdown if s.key] == ["summary", "experience", "education", "skills"]
    assert [s.key for s in plain if s.key] == ["summary", "experience", "education", "skills"]
    assert "Vaultic" in next(s for s in plain if s.key == "experience").body


def _check(text: str, key: str):  # type: ignore[no-untyped-def]
    return next((c for c in check_structure(text) if c.key == key), None)


LONG = " ".join(["word"] * 400)


def test_standard_headings_pass_and_a_missing_experience_section_fails() -> None:
    assert _check(render_markdown(_base()), "sections").status == "pass"

    no_experience = "## Summary\nHello.\n\n## Education\nSchool\n\n## Skills\nPython\n"
    section = _check(no_experience, "sections")
    assert section.status == "fail"
    assert "no Experience section" in section.detail


def test_missing_skills_or_education_warns_and_odd_headings_are_named() -> None:
    text = "## Experience\nDid things\n\n## My Journey\nStuff\n"

    section = _check(text, "sections")

    assert section.status == "warn"
    assert "no Skills section" in section.detail
    assert "no Education section" in section.detail
    assert "My Journey" in section.detail


def test_contact_details_pass_warn_or_fail() -> None:
    assert _check("a@b.co and +92 300 1234567", "contact").status == "pass"
    assert _check("reach me at (555) 123-4567 and me@site.dev", "contact").status == "pass"
    only_email = _check("me@site.dev", "contact")
    assert only_email.status == "warn"
    assert "add a phone number" in only_email.detail
    only_phone = _check("+92 300 1234567", "contact")
    assert "add an email address" in only_phone.detail
    none = _check(render_markdown(_base()), "contact")
    assert none.status == "fail"
    assert "doesn't store contact details" in none.detail


def test_dates_are_checked_for_presence_consistency_and_order() -> None:
    def experience(*lines: str) -> str:
        return "## Experience\n" + "\n".join(lines) + "\n"

    assert _check(render_markdown(_base()), "dates").status == "pass"
    assert _check(render_markdown(_base()), "order").status == "pass"

    assert _check(experience("Engineer, Acme"), "dates").status == "warn"
    mixed = experience("Mar 2024 - Present", "2020 - 2023")
    assert "mix" in _check(mixed, "dates").detail
    oldest_first = experience("Jan 2019 - Dec 2020", "Jan 2022 - Present")
    assert _check(oldest_first, "order").status == "warn"


def test_length_thresholds() -> None:
    assert _check("short resume text", "length").status == "warn"
    assert _check(LONG, "length").status == "pass"
    assert _check(" ".join(["word"] * 1300), "length").status == "warn"


def test_the_markdown_export_is_flagged_for_special_characters_and_markup() -> None:
    hazard = _check(render_markdown(_base()), "hazards")

    assert hazard.status == "warn"
    assert "—" in hazard.detail  # em dash in "Vaultic — University"
    assert "Markdown heading marker" in hazard.detail
    assert "ATS-safe version" in hazard.detail


def test_summarize_counts_each_status() -> None:
    counts = summarize(check_structure(render_markdown(_base())))

    assert set(counts) == {"pass", "warn", "fail"}
    assert counts["fail"] >= 1  # no contact details
    assert sum(counts.values()) == len(check_structure(render_markdown(_base())))


@pytest.mark.parametrize(
    ("raw", "safe"),
    [
        ("Mar 2024 – Present", "Mar 2024 - Present"),
        ("Title — Company", "Title - Company"),
        ("Dates · Remote", "Dates | Remote"),
        ("“quoted” and ‘single’", "\"quoted\" and 'single'"),
        ("a b", "a b"),
        ("wait…", "wait..."),
        ("• item", "- item"),
    ],
)
def test_typographic_symbols_become_plain_equivalents(raw: str, safe: str) -> None:
    assert to_ascii_safe(raw) == safe


def test_accented_letters_are_kept_because_stripping_them_would_misspell_names() -> None:
    assert to_ascii_safe("José Müller — Zürich") == "José Müller - Zürich"
    assert find_hazard_chars("José Müller") == {}
    assert find_hazard_chars("a — b · c —") == {"—": 2, "·": 1}


def test_other_non_letter_symbols_are_dropped() -> None:
    assert to_ascii_safe("Rating ★★★ done") == "Rating  done"


def test_markdown_markers_are_counted_by_heading_lines() -> None:
    assert markdown_marker_count("# A\ntext\n## B\n### C") == 3
    assert markdown_marker_count("plain text\nwith no headings") == 0


def test_the_ats_safe_render_has_plain_headings_and_no_hazards() -> None:
    plain = render_ats_plain(_base())

    assert plain.startswith("Aziz Ahmad\nML/AI Engineer\nLahore\n")
    for heading in ("SUMMARY", "EXPERIENCE", "EDUCATION", "SKILLS"):
        assert f"\n{heading}\n" in plain
    assert "Vaultic - University" in plain
    assert "Mar 2026 - Present" in plain
    assert "Jan 2025 - Dec 2025 | Remote" in plain  # a separator, not a middle dot
    assert plain.isascii()
    assert find_hazard_chars(plain) == {}
    assert markdown_marker_count(plain) == 0
    assert plain.rstrip().endswith("Flask, FastAPI, PostgreSQL")


def test_the_ats_safe_render_passes_the_hazard_check_the_markdown_one_fails() -> None:
    base = _base()

    assert _check(render_markdown(base), "hazards").status == "warn"
    assert _check(render_ats_plain(base), "hazards").status == "pass"
    assert _check(render_ats_plain(base), "sections").status == "pass"
    assert _check(render_ats_plain(base), "dates").status == "pass"


def test_user_text_with_typographic_symbols_is_cleaned_in_the_ats_safe_render() -> None:
    base = _base()
    base.experiences[0].description = "Built “fraud” detection — fast…"

    plain = render_ats_plain(base)

    assert 'Built "fraud" detection - fast...' in plain
    assert find_hazard_chars(plain) == {}


def test_keywords_work_against_the_ats_safe_text_too() -> None:
    base = _base()

    assert _states(render_ats_plain(base), base, "Flask", "FastAPI") == {
        "Flask": "in_context",
        "FastAPI": "listed_only",
    }


def test_a_run_of_years_is_not_mistaken_for_a_phone_number() -> None:
    assert _check("Attended 2018 2019 2020 2021 2022 school", "contact").status == "fail"
