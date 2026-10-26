---
name: tw-lynch-quant
description: Run or explain the Taiwan listed/OTC Lynch-proxy quantitative screen, including coverage, trading-day status, data-quality limits, and handoff to DSA deep analysis.
---

# Taiwan Lynch Quant Screen

Use `scripts/tw_lynch_screen.py` and `config/tw_lynch_quant.json` as the executable and rule source. Do not duplicate numeric thresholds in this skill.

## Workflow

1. Confirm the requested scope is TWSE listed plus TPEx OTC common stocks. The official company lists are the universe; ETFs, ETNs, warrants and emerging-board securities are excluded.
2. Run the deterministic two-stage screen. Treat exchange publication dates as the trading-day authority. Do not force a run on a non-trading day unless the user explicitly asks for a test.
3. Report the coverage counts from the JSON artifact. Never describe a run as “all Taiwan stocks covered” without showing the universe, official snapshot, history and institutional hit counts.
4. Explain the three scores separately: fundamental proxy (40), trend/breakout (40), and institutional flow (20). The configurable file is authoritative.
5. Pass only the selected `.TW`/`.TWO` symbols into the existing DSA deep-analysis flow and Telegram notifier. Preserve the original watchlist workflow.

## Boundaries

- Call the fundamental component a “Lynch proxy.” Exchange-wide PEG, debt ratio and free-cash-flow coverage is not available in this first stage; verify those fields during candidate deep analysis.
- Missing data is unknown, never zero-quality evidence. Keep the coverage and limitations in the result.
- Do not print, store, or place Telegram/LLM secrets in files. Read them only from environment variables or GitHub Actions Secrets.
- The output is research screening, not investment advice or an order signal.
