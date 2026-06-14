# Trading Desk OS Monetizable API Layer

This release turns the research app into an API-first product with:

- FastAPI backend
- API-key authentication
- Monthly usage metering / credit limits
- Admin user and API-key creation
- Stock analysis endpoint
- Scanner endpoint
- Daily report endpoint
- Market regime endpoint
- Recent signals endpoint
- SQLite persistence for users, keys, usage, requests, reports, and signals
- Docker / docker-compose deployment files

## 1. Install

```bash
pip install -r requirements-api.txt
```

## 2. Start API

```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

## 3. Create first API user/key

```bash
PYTHONPATH=. python scripts/create_api_key.py \
  --email customer@example.com \
  --name "First Customer" \
  --plan starter \
  --credits 10000
```

The key is shown once. Store it securely.

## 4. Call endpoints

```bash
export TDO_API_KEY="tdo_xxxxx"

curl -X POST http://127.0.0.1:8000/api/v1/analyze \
  -H "X-API-Key: $TDO_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"ticker":"NVDA"}'
```

Scanner:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/scanner \
  -H "X-API-Key: $TDO_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"tickers":["NVDA","AAPL","MSFT","AMD"],"max_names":4}'
```

Daily report:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/report/daily \
  -H "X-API-Key: $TDO_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"tickers":["NVDA","AAPL","MSFT","AMD","PLTR"],"title":"Daily Trading Desk Report"}'
```

Account / usage:

```bash
curl http://127.0.0.1:8000/api/v1/account -H "X-API-Key: $TDO_API_KEY"
curl http://127.0.0.1:8000/api/v1/usage -H "X-API-Key: $TDO_API_KEY"
```

## 5. Credit pricing model

Default endpoint credits:

| Endpoint | Credits |
|---|---:|
| `/api/v1/analyze` | 1 |
| `/api/v1/regime` | 1 |
| `/api/v1/signals/recent` | 1 |
| `/api/v1/scanner` | 25 |
| `/api/v1/report/daily` | 50 |

Suggested tiers:

| Plan | Monthly price | Credits |
|---|---:|---:|
| Free | $0 | 100 |
| Starter | $49 | 10,000 |
| Pro | $149 | 100,000 |
| Desk | $499+ | 1,000,000+ |

## 6. Admin endpoints

Set:

```bash
export TDO_ADMIN_BOOTSTRAP_KEY="change-this-admin-key"
```

Create user:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/admin/users \
  -H "X-Admin-Key: $TDO_ADMIN_BOOTSTRAP_KEY" \
  -H "Content-Type: application/json" \
  -d '{"email":"customer@example.com","name":"Customer","plan":"starter","monthly_credit_limit":10000}'
```

Create API key:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/admin/api-keys \
  -H "X-Admin-Key: $TDO_ADMIN_BOOTSTRAP_KEY" \
  -H "Content-Type: application/json" \
  -d '{"email":"customer@example.com","label":"prod-key"}'
```

## 7. Docker

```bash
docker compose up --build
```

## 8. Production notes

Before selling publicly:

1. Replace SQLite with Postgres for multi-instance deployment.
2. Add Redis for rate limiting if traffic grows.
3. Add Stripe webhooks to update `users.plan` and `users.monthly_credit_limit`.
4. Add terms of service and market-data licensing review.
5. Add monitoring and error alerts.
6. Keep forward-testing all signals in the `signals` table.

## 9. Monetization path

Start closed beta with 5-20 users:

- Provide API keys manually.
- Cap usage by monthly credits.
- Generate daily reports and signal history.
- Track endpoint usage and signal outcomes.
- Convert beta users to Starter/Pro once results and workflow are stable.
