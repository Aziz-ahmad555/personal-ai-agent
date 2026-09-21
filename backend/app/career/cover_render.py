"""Rendering a cover letter as plain text — pure code.

Only what the user has accepted appears. The salutation is the neutral "Dear Hiring Team," (a
recipient's name is never guessed), and the sign-off uses the profile's name if there is one.
Contact details aren't stored in the profile, so none are invented.
"""

SALUTATION = "Dear Hiring Team,"
SIGN_OFF = "Sincerely,"


def render_letter(name: str | None, paragraphs: list[str]) -> str:
    """The letter, or "" when there is nothing accepted yet to put in it."""
    body = [p.strip() for p in paragraphs if p.strip()]
    if not body:
        return ""
    lines = [SALUTATION, "", *[line for p in body for line in (p, "")], SIGN_OFF]
    if name:
        lines.append(name)
    return "\n".join(lines) + "\n"
