# Security policy

Please report vulnerabilities privately via **Security → Report a vulnerability** on this
repository (GitHub private vulnerability reporting). Don't open a public issue.

## Secrets

Never commit `.env`, `docker/gateway.env` or `docker/secrets/*`; they are gitignored. If a key is
ever exposed, rotate it at the provider first, then clean history.

## Trading safety

The bot defaults to an IBKR **paper** account and refuses mismatched mode, port and account IDs.
Changes that weaken the risk gate (`guardrail_trader/risk/`) or the paper/live checks
(`guardrail_trader/broker/ibkr.py`, `guardrail_trader/config.py`) need extra scrutiny in review.
