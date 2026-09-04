# Sablier

Sablier displays the remaining Claude and Codex allowances from their local CLI
logins on a Waveshare 2.7-inch e-Paper HAT V2 (264x176, black and white).

## Run

The current Linux user must be signed into Codex with ChatGPT and Claude Code,
and belong to the `spi` and `gpio` groups.

```bash
python3 main.py --preview preview.png --json
python3 main.py
```

The first command fetches live usage and creates a PNG without changing the
display. The second command performs a full e-paper refresh.

Sablier reads `~/.codex/auth.json` and `~/.claude/.credentials.json`. It never
logs tokens. When an access token is close to expiry, it follows the matching
CLI refresh flow and atomically writes rotated tokens back with mode `0600`.

The usage URLs are internal ChatGPT and Anthropic endpoints and have no public
stability guarantee. Future CLI updates may require adapting the parsers.

## Automatic refresh

Example systemd service and timer units are in `systemd/`. They run as the
logged-in `happylittle7` user every 15 minutes, so they can read that user's
Codex login and access the SPI/GPIO device groups. Install them only after the
manual display command succeeds.

## KEY4 manual refresh

`button_daemon.py` watches KEY4 on BCM GPIO 19. A press runs the same full
Claude/Codex refresh as `main.py`. The input uses the Raspberry Pi pull-up and
100 ms debounce; holding the button triggers only once until it is released.

Install `systemd/sablier-button.service` as a user service to keep the watcher
running. Concurrent timer and button refreshes are prevented by
`output/refresh.lock`.
