"""LLM client factory (Anthropic direct or OpenRouter) and USD cost accounting.

Both providers speak the Anthropic Messages API, so the agent code is identical:
  LLM_PROVIDER=anthropic   ANTHROPIC_API_KEY=...    CLAUDE_MODEL=claude-sonnet-5
  LLM_PROVIDER=openrouter  OPENROUTER_API_KEY=...   CLAUDE_MODEL=anthropic/claude-sonnet-5
"""
from __future__ import annotations

import os

import guardrail_trader.config  # noqa: F401  (loads .env; budgets must never silently fall back to defaults)

# USD per million tokens (input, output). Source: Anthropic pricing page / OpenRouter model pages, Sep 2026.
# OpenRouter charges the same token prices plus a ~5.5% fee when you buy credits.
PRICES: dict[str, tuple[float, float]] = {
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-opus-5": (5.0, 25.0),
    "anthropic/claude-sonnet-5": (2.0, 10.0),
    "anthropic/claude-haiku-4.5": (1.0, 5.0),
    "anthropic/claude-opus-5": (5.0, 25.0),
}
CACHE_WRITE_MULT = 1.25   # 5-minute cache write
CACHE_READ_MULT = 0.10    # cache hit
WEB_SEARCH_USD = 0.01     # $10 per 1,000 searches

DEFAULT_MODEL = {"anthropic": "claude-sonnet-5", "openrouter": "anthropic/claude-sonnet-5"}


def provider() -> str:
    p = os.getenv("LLM_PROVIDER", "anthropic").strip().lower()
    if p not in DEFAULT_MODEL:
        raise ValueError(f"LLM_PROVIDER must be one of {list(DEFAULT_MODEL)}, got {p!r}")
    return p


def model() -> str:
    m = os.getenv("CLAUDE_MODEL", "").strip() or DEFAULT_MODEL[provider()]
    if m not in PRICES:
        raise ValueError(f"No price known for model {m!r}; add it to guardrail_trader/llm.py PRICES "
                         f"so spend limits can be enforced.")
    return m


def make_client():
    import anthropic
    if provider() == "openrouter":
        key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if not key:
            raise ValueError("OPENROUTER_API_KEY is empty")
        return anthropic.Anthropic(base_url="https://openrouter.ai/api", auth_token=key, api_key=None,
                                   timeout=request_timeout_s(), max_retries=2)
    if not os.getenv("ANTHROPIC_API_KEY", "").strip():
        raise ValueError("ANTHROPIC_API_KEY is empty")
    return anthropic.Anthropic(timeout=request_timeout_s(), max_retries=2)


def request_timeout_s() -> float:
    """Per-request timeout. The SDK default is 10 minutes, long enough to eat a trading slot."""
    return float(os.getenv("LLM_REQUEST_TIMEOUT_S", "60"))


def cost_usd(model_id: str, usage) -> float:
    """Cost of one API response from its `usage` block."""
    p_in, p_out = PRICES[model_id]
    g = lambda name: float(getattr(usage, name, 0) or 0)  # noqa: E731
    searches = 0.0
    stu = getattr(usage, "server_tool_use", None)
    if stu is not None:
        searches = float(getattr(stu, "web_search_requests", 0) or 0)
    return (g("input_tokens") * p_in
            + g("cache_creation_input_tokens") * p_in * CACHE_WRITE_MULT
            + g("cache_read_input_tokens") * p_in * CACHE_READ_MULT
            + g("output_tokens") * p_out) / 1_000_000 + searches * WEB_SEARCH_USD


def run_budget_usd() -> float:
    return float(os.getenv("LLM_RUN_BUDGET_USD", "0.50"))


def monthly_budget_usd() -> float:
    return float(os.getenv("LLM_MONTHLY_BUDGET_USD", "5.00"))
