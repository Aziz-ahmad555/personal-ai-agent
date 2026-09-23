"""Red-team Track A, item 7: structural regression guards. These don't test behavior — they
scan source for a *shape* the app currently has and should never lose. Both patterns were
confirmed true by a red-team pass (an Explore agent's research read, verified directly against
the actual source before relying on it); this turns that one-time confirmation into something
that fails CI if a future change quietly breaks it.
"""

from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent / "app"

# The one place any LLM SDK client is constructed, by design (app.research.llm's
# GeminiLLMProvider/AnthropicLLMProvider) — both wrap generate_structured, a schema-constrained
# JSON-in/JSON-out call with no side-effecting tool ever bound to it (Anthropic's "tool use" is
# used purely as a JSON-shaping trick; nothing in the app executes what a model puts in a tool
# call). If any other module starts constructing a client directly, that's a new, unreviewed
# path for a model's output to reach something other than a JSON payload our own code verifies.
_ALLOWED_LLM_CLIENT_FILE = APP_ROOT / "research" / "llm.py"
_LLM_CLIENT_PATTERNS = ("genai.Client(", "AsyncAnthropic(")


def test_no_llm_sdk_client_is_constructed_outside_the_one_sanctioned_module() -> None:
    offenders = []
    for path in APP_ROOT.rglob("*.py"):
        if path == _ALLOWED_LLM_CLIENT_FILE:
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in _LLM_CLIENT_PATTERNS:
            if pattern in text:
                offenders.append(f"{path.relative_to(APP_ROOT.parent)}: {pattern}")

    assert not offenders, (
        "An LLM SDK client is being constructed outside app/research/llm.py — every LLM call "
        "in this app is supposed to go through generate_structured, never a raw client with "
        "its own tool-use/function-calling surface:\n" + "\n".join(offenders)
    )


def test_no_llm_call_site_binds_an_executable_tool() -> None:
    """generate_structured's own two implementations are allowed to mention "tool" (Anthropic's
    provider genuinely uses forced tool-use as a JSON-shaping trick) — what must never appear
    anywhere else is a tool/function definition wired to something that actually runs."""
    offenders = []
    for path in APP_ROOT.rglob("*.py"):
        if path == _ALLOWED_LLM_CLIENT_FILE:
            continue
        text = path.read_text(encoding="utf-8")
        if "tool_choice" in text or "input_schema" in text:
            offenders.append(str(path.relative_to(APP_ROOT.parent)))

    assert not offenders, (
        "Found tool-use/function-calling configuration outside app/research/llm.py — this "
        "would be a new path for a model to trigger code, not just return JSON:\n"
        + "\n".join(offenders)
    )
