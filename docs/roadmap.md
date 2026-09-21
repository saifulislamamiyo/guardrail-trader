# Roadmap

Ideas, not commitments.

| Idea | Why |
|---|---|
| Alerts (ntfy or Telegram) on kill switch, reconciliation failure or a silent scheduler | Unattended runs need someone told when they stop |
| OpenTelemetry traces per run and tool call | Standard observability instead of the journal alone |
| AWS hosting: EventBridge Scheduler → Step Functions → ECS Fargate, journal on S3 | No dependency on a Mac staying awake |
| IBKR Web API (OAuth) | Remove the IB Gateway process entirely |
| `doctor` preflight command | One check for gateway, ports, keys, config and journal |
| Options strategies | Explore later, with their own gate rules |

## Known limitations

- **Local hosting:** the Mac must stay awake with the lid open.
- **Whole shares only:** the IBKR API rejects fractional-share orders.
- **Delayed prices:** free-trial paper accounts get delayed (~15 min) market data.
- **Native IB Gateway:** needs a manual login after a reboot, and IBKR requires a fresh login weekly. The Docker mode automates this with IBC.
