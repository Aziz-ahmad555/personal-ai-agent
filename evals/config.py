"""Eval-harness configuration: paths, the eval database URL, and the per-model cost table.

The cost table is a small, checked-in estimate, not a billing-accurate figure — provider
pricing drifts (Groq's own model catalog changed once in the course of building this harness),
so every cost figure the harness prints is labeled "estimated" and traceable to this file.
Update the numbers here when a provider's published pricing changes; there is no live pricing
API this harness calls.
"""

import sys
from dataclasses import dataclass
from pathlib import Path

EVALS_ROOT = Path(__file__).resolve().parent
DATASETS_DIR = EVALS_ROOT / "datasets"
REPORTS_DIR = EVALS_ROOT / "reports"
BACKEND_ROOT = EVALS_ROOT.parent / "backend"

# Every eval module imports this one first (directly or via a bucket), so this is the one
# place that makes `import app.xxx` (the backend package) work regardless of which directory
# run_all.py was launched from.
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@dataclass(frozen=True)
class ModelPricing:
    # USD per 1,000 tokens.
    input_per_1k: float
    output_per_1k: float


# Prices as of the model defaults this project actually uses (app/config.py). These are
# published list prices at the time this file was written, not fetched live — treat every
# cost figure derived from this table as an estimate, and update it when it goes stale.
MODEL_PRICING: dict[str, ModelPricing] = {
    "openai/gpt-oss-120b": ModelPricing(input_per_1k=0.00015, output_per_1k=0.00060),
    "gemini-3.6-flash": ModelPricing(input_per_1k=0.00010, output_per_1k=0.00040),
    "claude-haiku-4-5-20251001": ModelPricing(input_per_1k=0.00100, output_per_1k=0.00500),
    # A distinct, usually-stronger judge model — see judge.py. Falls back to the active
    # provider's own model if this isn't set to something the harness recognizes.
    "llama-3.3-70b-versatile": ModelPricing(input_per_1k=0.00059, output_per_1k=0.00079),
}


def estimate_cost_usd(model: str, tokens_in: int | None, tokens_out: int | None) -> float | None:
    pricing = MODEL_PRICING.get(model)
    if pricing is None or tokens_in is None or tokens_out is None:
        return None
    return (tokens_in / 1000) * pricing.input_per_1k + (tokens_out / 1000) * pricing.output_per_1k


def derive_eval_database_url(database_url: str) -> str:
    """Swaps the real app's database name for a dedicated eval one on the same server —
    never runs eval data through the user's real personal_agent database. Postgres only
    (pgvector's cosine_distance operator doesn't exist on SQLite, and a real retrieval-hit-rate
    eval needs the real thing, not a stand-in)."""
    if "sqlite" in database_url:
        raise ValueError(
            "The eval harness needs a real Postgres database (pgvector's cosine_distance has "
            "no SQLite equivalent) — point DATABASE_URL at the project's own Postgres, not a "
            "sqlite URL. See docker-compose.yml at the repo root."
        )
    base, _, _ = database_url.rpartition("/")
    return f"{base}/personal_agent_evals"
