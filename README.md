# Sablier

Sablier displays the remaining Claude and Codex allowances from their local CLI
logins on a Waveshare 2.7-inch e-Paper HAT V2 (264x176, black and white).

## Run

The current Linux user must be signed into Codex with ChatGPT and Claude Code,
and belong to the `spi` and `gpio` groups.

```bash
python3 main.py --preview preview.png --json
python3 main.py --mode clock --preview clock.png
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

`main.py --daemon` is the single long-running process. KEY1 selects the Claude
and Codex usage screen, KEY2 selects a minute-resolution clock, and KEY3 is
reserved for a future mode. The last selected mode is restored after restart.
The usage mode refreshes every 5 minutes; the clock aligns updates to the next
wall-clock minute. Both use the V2 partial-update waveform between periodic full
refreshes that clear ghosting. The example user service is
`systemd/sablier.service`.

## KEY4 manual refresh

KEY1 through KEY4 use BCM GPIO 5, 6, 13, and 19. KEY4 forces a full refresh of
the active mode: it fetches fresh provider usage in usage mode and immediately
corrects the time in clock mode. The input uses the Raspberry Pi pull-up and
100 ms debounce; holding a button triggers only once. Concurrent refreshes are
prevented by `output/refresh.lock`.
