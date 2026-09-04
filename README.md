# Sablier

Sablier displays the remaining Claude and Codex allowances from their local CLI
logins on a Waveshare 2.7-inch e-Paper HAT V2 (264x176, black and white).

## Run

The current Linux user must be signed into Codex with ChatGPT and Claude Code,
and belong to the `spi` and `gpio` groups.

```bash
python3 main.py --preview preview.png --json
python3 main.py
python3 main.py --daemon
```

The first command fetches live usage and creates a PNG without changing the
display. The second command performs a full e-paper refresh.

Sablier reads `~/.codex/auth.json` and `~/.claude/.credentials.json`. It never
logs tokens. When an access token is close to expiry, it follows the matching
CLI refresh flow and atomically writes rotated tokens back with mode `0600`.

The usage URLs are internal ChatGPT and Anthropic endpoints and have no public
stability guarantee. Future CLI updates may require adapting the parsers.

## Daemon

`main.py --daemon` is the single long-running process. It refreshes once at
startup, every 5 minutes after the previous refresh, and whenever KEY4 is
pressed. The example user service is `systemd/sablier.service`.

## KEY4 manual refresh

The daemon watches KEY4 on BCM GPIO 19. A press runs the same full Claude/Codex
refresh as `main.py`. The input uses the Raspberry Pi pull-up and 100 ms
debounce; holding the button triggers only once. Concurrent daemon and manual
refreshes are prevented by `output/refresh.lock`.
