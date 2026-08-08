"""
google_sheet_functions.py
--------------------------
Backend data-access layer for the SKCS Client Management System.

This version talks to Google Sheets THROUGH a Google Apps Script Web App
(see Code.gs) over plain HTTPS - it does NOT use gspread or a service
account key. This avoids the "Service account key creation is disabled"
organization policy entirely, since no key is ever created.

Sheet architecture (7 tabs in ONE Google Spreadsheet):

    Client_Master     -> one row per client (permanent identity data)
    Services_Catalog  -> one row per service type offered (ITR, GST-MON, ...)
    Work_Tracker      -> one row per engagement / work item (the year/period
                          is DATA here, not a column name)
    Invoices          -> one row per invoice
    Payments          -> one row per payment received
    Update_History    -> audit trail of field changes
    Staff_Member       -> list of staff for "Assigned To" dropdowns

Required st.secrets structure (Streamlit Cloud -> App -> Settings -> Secrets):

    webapp_url = "https://script.google.com/macros/s/XXXXXXXX/exec"
    webapp_token = "the-same-long-random-string-you-put-in-Code.gs"

    [users]
    admin = "your-login-password"
    suraj = "another-password"

See README.md for how to deploy Code.gs and get the webapp_url.
"""

import time

import pandas as pd
import requests
import streamlit as st

# =====================================================================
# SHEET / COLUMN DEFINITIONS
# =====================================================================

CLIENT_MASTER = "Client_Master"
SERVICES_CATALOG = "Services_Catalog"
WORK_TRACKER = "Work_Tracker"
INVOICES = "Invoices"
PAYMENTS = "Payments"
UPDATE_HISTORY = "Update_History"
STAFF_MEMBER = "Staff_Member"

CLIENT_MASTER_COLS = [
    "Client ID", "Salutation", "Client Name", "PAN", "GSTIN",
    "Mobile", "Email", "Address", "Client Type", "Client Source",
    "Default Assigned To", "Client Folder Reference", "Client Status",
    "Onboarded On",
]

SERVICES_CATALOG_COLS = [
    "Service Code", "Service Name", "Frequency", "Default Fee", "Status Options",
]

WORK_TRACKER_COLS = [
    "Work ID", "Client ID", "Service Code", "Period", "Status",
    "Assigned To", "Start Date", "Due Date", "Completed Date",
    "Brief Remarks", "Next Follow Up",
]

INVOICES_COLS = [
    "Invoice No", "Invoice Date", "Client ID", "Work ID(s)", "Description",
    "Amount", "GST Applicable", "GST Amount", "Total", "Status",
]

PAYMENTS_COLS = [
    "Payment ID", "Date", "Client ID", "Invoice No", "Amount",
    "Mode", "Received By", "Remarks",
]

UPDATE_HISTORY_COLS = [
    "Date", "Time", "User", "Client ID", "Work ID",
    "Field Changed", "Old Value", "New Value",
]

STAFF_MEMBER_COLS = ["User Name", "Role"]

TERMINAL_STATUSES = {"Filed", "e-Verified", "Completed", "Inactive", "Closed"}

DEFAULT_STATUS_OPTIONS = [
    "Documents Awaited", "Documents Received", "Under Preparation",
    "Query Raised", "Ready for Filing", "Filed", "e-Verified",
    "Completed", "Inactive",
]


# =====================================================================
# HTTP LAYER
# =====================================================================

def _webapp_url() -> str:
    return st.secrets["webapp_url"]


def _token() -> str:
    return st.secrets["webapp_token"]


def _get(action: str, attempts: int = 3, delay: float = 1.5, **params) -> dict:
    params = dict(params)
    params["action"] = action
    params["token"] = _token()
    last_err = None
    for i in range(attempts):
        try:
            resp = requests.get(_webapp_url(), params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                raise RuntimeError(f"Apps Script error: {data['error']}")
            return data
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(delay * (i + 1))
    raise last_err


def _post(payload: dict, attempts: int = 3, delay: float = 1.5) -> dict:
    payload = dict(payload)
    payload["token"] = _token()
    last_err = None
    for i in range(attempts):
        try:
            resp = requests.post(_webapp_url(), json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                raise RuntimeError(f"Apps Script error: {data['error']}")
            return data
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(delay * (i + 1))
    raise last_err


# =====================================================================
# GENERIC READ / WRITE (cached briefly so a single page load doesn't
# make redundant round-trips to Apps Script; cleared after any write)
# =====================================================================

@st.cache_data(ttl=15, show_spinner=False)
def _load_sheet(sheet_name: str, cols: tuple) -> pd.DataFrame:
    cols = list(cols)
    data = _get("read", sheet=sheet_name)
    rows = data.get("rows", [])
    df = pd.DataFrame(rows)
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    return df[cols] if len(df) else pd.DataFrame(columns=cols)


def _ensure_sheet(sheet_name: str, cols: list):
    _post({"action": "ensure_sheet", "sheet": sheet_name, "headers": cols})


def _save_sheet(sheet_name: str, df: pd.DataFrame, cols: list):
    df = df.copy()
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    df = df[cols].fillna("").astype(str)
    _post({"action": "overwrite_sheet", "sheet": sheet_name, "headers": cols, "rows": df.values.tolist()})
    st.cache_data.clear()


def _append_row(sheet_name: str, row: dict, cols: list):
    ordered = {c: str(row.get(c, "")) for c in cols}
    _post({"action": "append_row", "sheet": sheet_name, "headers": cols, "row": ordered})
    st.cache_data.clear()


def _update_row_by_id(sheet_name: str, cols: list, id_col: str, id_val: str, updates: dict):
    result = _post({
        "action": "update_row", "sheet": sheet_name,
        "id_col": id_col, "id_val": str(id_val),
        "updates": {k: str(v) for k, v in updates.items()},
    })
    st.cache_data.clear()
    return result.get("found", False)


def _next_id(df: pd.DataFrame, id_col: str, prefix: str, width: int = 6) -> str:
    if id_col not in df.columns or df.empty:
        return f"{prefix}{str(1).zfill(width)}"
    nums = df[id_col].astype(str).str.replace(prefix, "", regex=False)
    nums = pd.to_numeric(nums, errors="coerce")
    last = nums.max()
    last = 0 if pd.isna(last) else int(last)
    return f"{prefix}{str(last + 1).zfill(width)}"


def log_history(user, client_id, work_id, field, old_value, new_value):
    if str(old_value) == str(new_value):
        return
    from datetime import datetime
    now = datetime.now()
    _append_row(
        UPDATE_HISTORY,
        {
            "Date": now.strftime("%d-%m-%Y"),
            "Time": now.strftime("%H:%M:%S"),
            "User": user,
            "Client ID": client_id,
            "Work ID": work_id,
            "Field Changed": field,
            "Old Value": old_value,
            "New Value": new_value,
        },
        UPDATE_HISTORY_COLS,
    )


# =====================================================================
# CLIENT MASTER
# =====================================================================

def load_clients() -> pd.DataFrame:
    return _load_sheet(CLIENT_MASTER, tuple(CLIENT_MASTER_COLS))


def save_clients(df: pd.DataFrame):
    _save_sheet(CLIENT_MASTER, df, CLIENT_MASTER_COLS)


def add_client(row: dict) -> str:
    from datetime import datetime
    df = load_clients()
    new_id = _next_id(df, "Client ID", "SK")
    row["Client ID"] = new_id
    row.setdefault("Client Status", "Active")
    row.setdefault("Onboarded On", datetime.now().strftime("%d-%m-%Y"))
    _append_row(CLIENT_MASTER, row, CLIENT_MASTER_COLS)
    return new_id


def update_client(client_id: str, updates: dict):
    _update_row_by_id(CLIENT_MASTER, CLIENT_MASTER_COLS, "Client ID", client_id, updates)


# =====================================================================
# SERVICES CATALOG
# =====================================================================

def load_services() -> pd.DataFrame:
    df = _load_sheet(SERVICES_CATALOG, tuple(SERVICES_CATALOG_COLS))
    if df.empty:
        defaults = [
            {"Service Code": "ITR", "Service Name": "Income Tax Return Filing",
             "Frequency": "Annual", "Default Fee": "", "Status Options": ",".join(DEFAULT_STATUS_OPTIONS)},
            {"Service Code": "GST-MON", "Service Name": "GST Monthly Return (GSTR-1/3B)",
             "Frequency": "Monthly", "Default Fee": "",
             "Status Options": "Data Awaited,Data Received,Return Prepared,Filed,Query Raised"},
            {"Service Code": "GST-QTR", "Service Name": "GST Quarterly Return (QRMP)",
             "Frequency": "Quarterly", "Default Fee": "",
             "Status Options": "Data Awaited,Data Received,Return Prepared,Filed,Query Raised"},
            {"Service Code": "TDS", "Service Name": "TDS Return Filing",
             "Frequency": "Quarterly", "Default Fee": "",
             "Status Options": "Data Awaited,Return Prepared,Filed"},
            {"Service Code": "STAT-AUDIT", "Service Name": "Corporate Statutory Audit",
             "Frequency": "Annual", "Default Fee": "",
             "Status Options": "Planning,Fieldwork,Draft Report,Signed,Completed"},
            {"Service Code": "INT-AUDIT", "Service Name": "Internal Audit",
             "Frequency": "Annual", "Default Fee": "",
             "Status Options": "Planning,Fieldwork,Draft Report,Completed"},
            {"Service Code": "RERA", "Service Name": "RERA Compliance",
             "Frequency": "Quarterly", "Default Fee": "",
             "Status Options": "Data Awaited,Filed,Query Raised,Completed"},
            {"Service Code": "ADVISORY", "Service Name": "Accounts Advisory",
             "Frequency": "One-time", "Default Fee": "",
             "Status Options": "In Progress,Completed"},
        ]
        for row in defaults:
            _append_row(SERVICES_CATALOG, row, SERVICES_CATALOG_COLS)
        df = _load_sheet(SERVICES_CATALOG, tuple(SERVICES_CATALOG_COLS))
    return df


def add_service(row: dict):
    _append_row(SERVICES_CATALOG, row, SERVICES_CATALOG_COLS)


def status_options_for(service_code: str, services_df: pd.DataFrame) -> list:
    match = services_df[services_df["Service Code"] == service_code]
    if match.empty:
        return DEFAULT_STATUS_OPTIONS
    raw = str(match.iloc[0].get("Status Options", "")).strip()
    if not raw:
        return DEFAULT_STATUS_OPTIONS
    return [s.strip() for s in raw.split(",") if s.strip()]


# =====================================================================
# WORK TRACKER
# =====================================================================

def load_work() -> pd.DataFrame:
    return _load_sheet(WORK_TRACKER, tuple(WORK_TRACKER_COLS))


def save_work(df: pd.DataFrame):
    _save_sheet(WORK_TRACKER, df, WORK_TRACKER_COLS)


def add_work_item(row: dict) -> str:
    df = load_work()
    new_id = _next_id(df, "Work ID", "WK")
    row["Work ID"] = new_id
    _append_row(WORK_TRACKER, row, WORK_TRACKER_COLS)
    return new_id


def update_work_item(work_id: str, updates: dict):
    _update_row_by_id(WORK_TRACKER, WORK_TRACKER_COLS, "Work ID", work_id, updates)


# =====================================================================
# INVOICES
# =====================================================================

def load_invoices() -> pd.DataFrame:
    return _load_sheet(INVOICES, tuple(INVOICES_COLS))


def add_invoice(row: dict) -> str:
    df = load_invoices()
    new_no = _next_id(df, "Invoice No", "INV")
    row["Invoice No"] = new_no
    row.setdefault("Status", "Unpaid")
    _append_row(INVOICES, row, INVOICES_COLS)
    return new_no


def update_invoice(invoice_no: str, updates: dict):
    _update_row_by_id(INVOICES, INVOICES_COLS, "Invoice No", invoice_no, updates)


# =====================================================================
# PAYMENTS
# =====================================================================

def load_payments() -> pd.DataFrame:
    return _load_sheet(PAYMENTS, tuple(PAYMENTS_COLS))


def add_payment(row: dict) -> str:
    from datetime import datetime
    df = load_payments()
    new_id = _next_id(df, "Payment ID", "PMT")
    row["Payment ID"] = new_id
    row.setdefault("Date", datetime.now().strftime("%d-%m-%Y"))
    _append_row(PAYMENTS, row, PAYMENTS_COLS)
    return new_id


# =====================================================================
# STAFF
# =====================================================================

def load_staff() -> pd.DataFrame:
    df = _load_sheet(STAFF_MEMBER, tuple(STAFF_MEMBER_COLS))
    if df.empty:
        return pd.DataFrame([{"User Name": "Admin", "Role": "Admin"}])
    return df


def add_staff(user_name: str, role: str):
    _append_row(STAFF_MEMBER, {"User Name": user_name, "Role": role}, STAFF_MEMBER_COLS)


# =====================================================================
# UPDATE HISTORY (read only from app side)
# =====================================================================

def load_history() -> pd.DataFrame:
    return _load_sheet(UPDATE_HISTORY, tuple(UPDATE_HISTORY_COLS))
