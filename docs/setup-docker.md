# Docker setup

Three containers replace the IB Gateway app, the scheduler and the dashboard. Only the keep-awake
job stays on the host, because a container can't stop the Mac sleeping.

## Prerequisites

- Docker Desktop (Apple silicon or Intel)
- An IBKR **paper** login. Paper logins don't ask for 2FA, so IBC can log in unattended.
- The repo cloned and a `.venv` created (used by keep-awake and the operator scripts): see
  [Native setup → Install](setup-native.md#1-install).

## 1. Provide secrets (all gitignored)

```bash
cp .env.example .env                                  # bot settings + API key
cp docker/gateway.env.example docker/gateway.env      # TWS_USERID=<paper username>
mkdir -p docker/secrets
printf '%s' 'your-ibkr-password' > docker/secrets/tws_password.txt
printf '%s' 'a-vnc-password'     > docker/secrets/vnc_password.txt
chmod 600 docker/secrets/*
```

The IBKR password is mounted as a Docker secret (`/run/secrets/tws_password`), not an environment
variable. The bot's `IBKR_HOST`/`IBKR_PORT` in `.env` are overridden by compose to `ib-gateway:4004`.

## 2. Switch the host to Docker mode

```bash
scripts/launchd.sh docker-mode   # removes native scheduler + dashboard agents, keeps keep-awake
```

!!! warning "One IBKR session per username"
    Quit the native IB Gateway app first. If both log in with the same username, one session gets
    kicked. The container is set to `EXISTING_SESSION_DETECTED_ACTION=secondary`, so it backs off
    rather than kicking you.

## 3. Build and start

```bash
docker compose build
docker compose up -d
docker compose ps                 # bot becomes "healthy" once the scheduler heartbeat is fresh
docker compose logs -f ib-gateway # watch IBC log in
```

Check the connection from inside the bot container:

```bash
docker compose exec bot python scripts/check_connection.py
```

To watch the gateway's login screen, open a VNC client at `vnc://127.0.0.1:15900`.

## 4. Recommended Docker Desktop settings

| Setting | Value | Why |
|---|---|---|
| Start Docker Desktop when you sign in | on | containers come back after a reboot (`restart: unless-stopped`) |
| Open Docker Dashboard at startup | off | nothing to look at unattended |
| Automatically download updates | off | avoid surprise restarts during market hours |
| Memory | 2 GB or more | the three containers use about 450 MB together |

## Rollback to native

```bash
docker compose down
# open IB Gateway and log in to Paper
scripts/launchd.sh install
```

The journal is the same bind-mounted file, so no data moves.
