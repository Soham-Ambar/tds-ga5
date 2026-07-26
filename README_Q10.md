# Q10 — A2A Invoice Agent

Implements the A2A 1.0 HTTP+JSON protocol for invoice action processing.

## Routes

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/.well-known/agent-card.json` | No | Agent Card |
| POST | `/a2a/message:send` | Bearer | Send message (batch or results) |
| GET | `/a2a/tasks` | Bearer | List tasks for authenticated user |
| GET | `/a2a/tasks/{taskId}` | Bearer | Get a specific task |
| POST | `/a2a/tasks/{taskId}:cancel` | Bearer | Cancel a task |

## Headers

- `Authorization: Bearer <token>`
- `A2A-Version: 1.0`
- `Content-Type: application/a2a+json`

## Task Lifecycle

```
INPUT_REQUIRED → COMPLETED
INPUT_REQUIRED → CANCELED
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `A2A_BASE_URL` | — | Base URL for agent card |
| `A2A_BEARER_TOKEN` | `ga5-invoice-token` | Bearer token for auth |
| `Q10_DB_PATH` | `q10_a2a.sqlite3` | SQLite database path |
| `AI_API_BASE` | — | OpenAI-compatible API base URL |
| `AI_API_KEY` | — | API key |
| `AI_MODEL` | — | Model name |
| `AI_TIMEOUT_SECONDS` | `30` | AI request timeout |
| `Q10_FAKE_AI` | — | Set to `1` for deterministic fake AI |

## Run Tests

```bash
python test_q10.py
```
