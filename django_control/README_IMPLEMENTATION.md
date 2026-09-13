# TDOS Django Control Plane — Phase 1

Django becomes the control plane; FastAPI remains the analytics engine.

## Flow
SwiftUI/Streamlit -> Django JWT -> quota check -> FastAPI -> persist AnalysisRecord + UsageEvent -> response.

## Suggested repo layout
```
pro_trading_desk/
  backend/              # existing FastAPI
  analysis_service.py   # unchanged analytics
  django_control/
    manage.py
    tdos_control/
    accounts/
    usage/
    research/
```

## 1. Install
```bash
cd django_control
pip install -r requirements-django.txt
```

## 2. Environment
Copy `.env.example` values into your shell/hosting environment. Generate three independent secrets:
```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```
Use separate values for `DJANGO_SECRET_KEY`, `DJANGO_JWT_SIGNING_KEY`, and `FASTAPI_INTERNAL_KEY`. The same `FASTAPI_INTERNAL_KEY` must be configured on Django and FastAPI.

## 3. Database
```bash
python manage.py makemigrations accounts usage research
python manage.py migrate
python manage.py createsuperuser
```

## 4. Run Django
```bash
python manage.py runserver 0.0.0.0:9000
```
Admin: `http://127.0.0.1:9000/admin/`
Create selected beta users here. There is intentionally no public signup endpoint.

## 5. Run FastAPI
```bash
export FASTAPI_INTERNAL_KEY='same-secret-as-django'
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```
Copy `backend_internal_auth.py` into `backend/internal_auth.py` and protect your existing compact route using the included patch example. Do not rewrite `analysis_service.py`.

## 6. Test login
```bash
curl -X POST http://127.0.0.1:9000/api/auth/login/ \
  -H 'Content-Type: application/json' \
  -d '{"username":"YOUR_USER","password":"YOUR_PASSWORD"}'
```
Response contains `access` and `refresh`.

## 7. Test account
```bash
curl http://127.0.0.1:9000/api/account/ \
  -H 'Authorization: Bearer ACCESS_TOKEN'
```

## 8. Test analysis through Django
```bash
curl -X POST http://127.0.0.1:9000/api/analysis/compact/ \
  -H 'Authorization: Bearer ACCESS_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{"ticker":"NVDA","persist_signal":true}'
```
Django returns the existing analytics JSON plus `_account` usage metadata.

## 9. iOS change
Replace the hard-coded `X-API-Key` workflow with `Authorization: Bearer <access token>`. Store access/refresh tokens in iOS Keychain. The iOS base URL should point to Django, not FastAPI.

## 10. PostgreSQL / Render
When ready, provision PostgreSQL and set `DATABASE_URL=postgresql://...`. Django owns the schema. Keep FastAPI private behind Django.

## Phase 2 after this works
Password-reset flow, invitation email, watchlists, portfolios, scanner proxy, migration of historical SQLite signals, and eventual billing.
