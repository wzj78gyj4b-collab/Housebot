# Housebot (Go migration)

This is an initial Go implementation of the existing Housebot Telegram bot. It keeps the original Python files intact while the migration is reviewed.

## Features in this migration branch

- Telegram Bot API long polling
- `/start` command
- Gemini API integration using HTTP with request timeouts
- Basic group mention gating and a moderation decision path
- Optional Telegram numeric admin allowlist via `TELEGRAM_ADMIN_IDS`
- Bounded concurrent message handling and graceful shutdown

## Requirements

- Go 1.23+
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- A Google Gemini API key

## Run locally

1. Copy `.env.example` to `.env`.
2. Set `TELEGRAM_BOT_TOKEN`, `AI_API_KEY`, and optionally `TELEGRAM_ADMIN_IDS`.
3. Export the variables in your shell (the Go program intentionally does not load `.env` automatically):
   `set -a && source .env && set +a`
4. Run `go run .`.

Never commit a real `.env` file or API keys. Rotate credentials immediately if they were exposed.

## Important limitations before production

- Moderation decisions are AI-generated and may be wrong. Review policy and test against real examples before enabling message deletion in production.
- Telegram deletion requires appropriate bot permissions in groups.
- Admin command is only a starter guard; operational admin actions are not implemented yet.
- Add automated tests, dependency/security scanning, and deployment secrets before production.
- Set `TELEGRAM_BOT_USERNAME` to the bot username without `@` so group mentions are detected reliably.
- Keep Telegram and Gemini API keys in the host's secret manager, not in GitHub source files.
