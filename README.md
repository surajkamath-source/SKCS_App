# SKCS Client Management System (v2 — no service account needed)

This version connects to Google Sheets through a small **Google Apps Script
Web App** instead of a service account key. This completely avoids the
"Service account key creation is disabled" organization policy error, since
no key is ever created — Apps Script runs under your own Google login.

See `SKCS_App_Redesign_Proposal.md` for the full design rationale behind the
sheet structure.

## Files

| File | Purpose | Where it runs |
|---|---|---|
| `Code.gs` | The API that reads/writes your Google Sheet | Inside Google (Apps Script), NOT in your GitHub repo |
| `app.py` | Main Streamlit app (all pages/navigation) | Streamlit Cloud |
| `google_sheet_functions.py` | Talks to Code.gs over HTTPS | Streamlit Cloud |
| `invoice_pdf.py` | Invoice PDF generator | Streamlit Cloud |
| `migrate_old_sheet.py` | One-time script to migrate your old `Client_Data` sheet | Your laptop |
| `requirements.txt` | Python dependencies | Streamlit Cloud |

## Step 1 — Deploy the Apps Script (Code.gs)

This is the part that replaces the service account entirely.

1. Open your Google Sheet (create a new one, or reuse your existing file).
2. Menu: **Extensions → Apps Script**. A new tab opens with a code editor.
3. Delete the placeholder `function myFunction() {}` code, and paste in the
   entire contents of `Code.gs`.
4. Near the top, fill in two values:
   - `SPREADSHEET_ID` — copy this from your Sheet's URL: the long string
     between `/d/` and `/edit`.
   - `SECRET_TOKEN` — make up a long random string (20-40 random
     letters/numbers). This acts as a password between your app and this
     script — nobody else can use your API without it. Do not reuse a
     password you use elsewhere.
5. Click the **Save** icon (or Ctrl+S).
6. Click **Deploy → New deployment**.
7. Click the gear icon next to "Select type" → choose **Web app**.
8. Set:
   - Execute as: **Me** (your Google account)
   - Who has access: **Anyone**
     *(This sounds alarming, but nobody can do anything without your
     SECRET_TOKEN — see the security note in Code.gs. "Anyone" is required
     here because Streamlit's server has no Google login of its own.)*
9. Click **Deploy**. The first time, Google will show an authorization
   screen ("Google hasn't verified this app") — this is expected, since
   it's your own personal script. Click **Advanced → Go to [project name]
   (unsafe) → Allow**.
10. Copy the **Web app URL** shown (starts with
    `https://script.google.com/macros/s/...../exec`). You'll need this in
    Step 3.

**To test it worked:** in the Apps Script editor, use the function dropdown
near the top (next to Run/Debug) to select `testConnection`, then click
**Run**. Check **View → Logs** — it should print "Connected OK to: <your
sheet's name>" with no errors.

## Step 2 — GitHub repository

Same as before — create a public repo and upload `app.py`,
`google_sheet_functions.py`, `invoice_pdf.py`, `requirements.txt`, and your
firm logo if you have one. **`Code.gs` and `migrate_old_sheet.py` do NOT go
in the GitHub repo** — `Code.gs` lives only inside Google Apps Script, and
`migrate_old_sheet.py` (once you fill in your real token) should stay only
on your laptop.

## Step 3 — Streamlit secrets

Much simpler now — no service account block at all.

```toml
webapp_url = "https://script.google.com/macros/s/XXXXXXXXXXXX/exec"
webapp_token = "the-exact-same-random-string-you-put-in-Code.gs"

[users]
admin = "choose-a-strong-password"
suraj = "another-password"
```

Locally, put this in `.streamlit/secrets.toml` (add it to `.gitignore` —
never commit it). On Streamlit Community Cloud, paste the same block into
**App → Settings → Secrets**.

## Step 4 — Deploy on Streamlit Community Cloud

1. Go to [share.streamlit.io](https://share.streamlit.io), sign in with
   GitHub.
2. **New app** → pick your repo/branch → main file path `app.py` → Deploy.
3. Once deployed, go to **Settings → Secrets** and paste the block from
   Step 3.
4. Reboot the app. First load auto-creates the 7 sheet tabs if missing.

## Step 5 — Run locally first (recommended before going live)

```bash
pip install -r requirements.txt
streamlit run app.py
```

Make sure `.streamlit/secrets.toml` exists locally with the same values as
Step 3 before running.

## Migrating your old data

1. Rename your existing `Client_Data` tab to `Client_Data_OLD` (keep it as
   backup — the migration script only reads from it).
2. Open `migrate_old_sheet.py`, fill in `WEBAPP_URL` and `WEBAPP_TOKEN`
   (same values as Step 3) at the top.
3. Run it locally: `python migrate_old_sheet.py`
4. Check the new `Client_Master`, `Work_Tracker`, `Invoices`, `Payments`
   tabs before deleting `Client_Data_OLD`.

## Adding new users / staff

- **Login access**: add a line under `[users]` in secrets.
- **"Assigned To" dropdown**: add via the **Staff** page in the app.

## Extending to GST / other services

Go to **Services Catalog** in the app and add a row (e.g. `GST-MON`, `GST
Monthly Return`, Monthly frequency) — no code or sheet-schema change
needed. It's immediately selectable in **Add Work Item** and **Billing**.

## If something stops working

- **"Apps Script error: Unauthorized"** — your `webapp_token` in Streamlit
  secrets doesn't match `SECRET_TOKEN` in `Code.gs`. They must be identical.
- **Blank data / errors reading sheets** — open the Apps Script editor,
  run `testConnection` again, check `SPREADSHEET_ID` is still correct.
- **Changed `SECRET_TOKEN` in Code.gs** — you must redeploy: **Deploy →
  Manage deployments → pencil icon → Version: New version → Deploy**, then
  update Streamlit's secrets to match.
- **Apps Script daily quota** — the free tier allows generous daily quota
  (well beyond what a 250-client firm will use in normal browsing), but if
  you ever see quota errors, it resets after 24 hours.
