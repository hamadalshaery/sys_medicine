# Pharmacy Web Portal

FastAPI backend + Jinja2 frontend for pharmacy inventory, customer accounts, admin dashboard, Excel import, barcode search, and PDF invoices.

## Setup

1. Create a virtual environment:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

2. Install requirements:

   ```powershell
   pip install -r requirements.txt
   ```

3. Create `.env` from `.env.example` and update values.

4. Run the app locally:

   ```powershell
   uvicorn app.main:app --reload
   ```

5. Open http://127.0.0.1:8000

## Netlify Deployment

- The Netlify function entrypoint is `netlify/functions/api.py`.
- Use `netlify.toml` to publish static assets from `frontend/build` and serve functions from `netlify/functions`.
- Set environment variables in Netlify dashboard:
  - `DATABASE_URL`
  - `JWT_SECRET`
  - `ADMIN_USERNAME`
  - `ADMIN_PASSWORD`

## External Database Example

For Supabase/PostgreSQL, use a URL like:

```text
postgresql+pg8000://<DB_USER>:<DB_PASS>@<PROJECT_REF>.supabase.co:5432/postgres
```

Keep secrets out of source control and only in Netlify environment settings.

## Notes

- Uses SQLite (`pharmacy.db`) by default.
- Admin login is created automatically if missing.
- Excel import supports medicine and customer sheets.
- Barcode scanner uses `html5-qrcode` in the browser.
