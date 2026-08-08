import streamlit as st
import pandas as pd
from datetime import date, timedelta, datetime

import google_sheet_functions as gsf
from invoice_pdf import generate_invoice_pdf

st.set_page_config(page_title="SKCS Client Management System", page_icon="📋", layout="wide")

# =====================================================================
# LOGIN
# =====================================================================

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "logged_user" not in st.session_state:
    st.session_state.logged_user = ""

if not st.session_state.logged_in:
    st.title("🔐 SKCS Client Management System")
    st.markdown("### Please Login")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    if st.button("🔑 Login", use_container_width=True):
        users = st.secrets["users"]
        if username in users and users[username] == password:
            st.session_state.logged_in = True
            st.session_state.logged_user = username
            st.rerun()
        else:
            st.error("Invalid Username or Password")
    st.stop()

logged_user = st.session_state.logged_user

# =====================================================================
# SIDEBAR
# =====================================================================

st.sidebar.success(f"👤 {logged_user}")
if st.sidebar.button("🚪 Logout"):
    st.session_state.logged_in = False
    st.session_state.logged_user = ""
    st.rerun()

menu = st.sidebar.radio(
    "Navigation",
    [
        "Dashboard",
        "Clients",
        "Add Client",
        "Work Tracker",
        "Add Work Item",
        "Billing",
        "Record Payment",
        "Fee Recovery / Aging",
        "Follow-Ups",
        "Services Catalog",
        "Staff",
        "Update History",
    ],
)

if st.sidebar.button("🔄 Refresh data"):
    st.cache_data.clear()
    st.rerun()

# =====================================================================
# LOAD CORE DATA (shared across pages)
# =====================================================================

clients_df = gsf.load_clients()
services_df = gsf.load_services()
work_df = gsf.load_work()
invoices_df = gsf.load_invoices()
payments_df = gsf.load_payments()
staff_df = gsf.load_staff()

staff_options = sorted(staff_df["User Name"].dropna().unique().tolist()) or ["Admin"]
service_options = services_df["Service Code"].dropna().unique().tolist()


def client_label_map():
    return {
        row["Client ID"]: f"{row['Client Name']} ({row['Client ID']})"
        for _, row in clients_df.iterrows()
    }


def invoice_due_amount(invoice_row, pay_df):
    paid = pd.to_numeric(
        pay_df[pay_df["Invoice No"] == invoice_row["Invoice No"]]["Amount"],
        errors="coerce",
    ).fillna(0).sum()
    total = pd.to_numeric(invoice_row.get("Total", 0), errors="coerce")
    total = 0 if pd.isna(total) else total
    return max(total - paid, 0), paid, total


# =====================================================================
# DASHBOARD
# =====================================================================

if menu == "Dashboard":
    st.title("📋 SKCS Client Management System")

    active_clients = clients_df[clients_df["Client Status"].astype(str).str.strip().str.lower() != "inactive"]
    inactive_clients = len(clients_df) - len(active_clients)

    active_work = work_df[~work_df["Status"].astype(str).isin(gsf.TERMINAL_STATUSES)]

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Active Clients", len(active_clients))
    c2.metric("Inactive Clients", inactive_clients)
    c3.metric("Open Work Items", len(active_work))
    c4.metric("Services Offered", len(services_df))
    c5.metric("Unpaid/Partial Invoices", len(invoices_df[invoices_df["Status"] != "Paid"]) if len(invoices_df) else 0)

    st.divider()

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("📊 Open Work by Status")
        if len(active_work):
            summary = active_work.groupby("Status").size().reset_index(name="Count").sort_values("Count", ascending=False)
            st.dataframe(summary, use_container_width=True, hide_index=True)
        else:
            st.info("No open work items.")

    with col2:
        st.subheader("👨‍💼 Work Allocation")
        if len(active_work):
            alloc = active_work.groupby("Assigned To").size().reset_index(name="Open Items").sort_values("Open Items", ascending=False)
            st.dataframe(alloc, use_container_width=True, hide_index=True)
        else:
            st.info("No open work items.")

    st.divider()
    st.subheader("🧾 Service-wise Open Work")
    if len(active_work):
        svc_summary = active_work.groupby("Service Code").size().reset_index(name="Open Items").sort_values("Open Items", ascending=False)
        st.dataframe(svc_summary, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("💰 Billing Snapshot")
    if len(invoices_df):
        total_billed = pd.to_numeric(invoices_df["Total"], errors="coerce").fillna(0).sum()
        total_received = pd.to_numeric(payments_df["Amount"], errors="coerce").fillna(0).sum() if len(payments_df) else 0
        outstanding = max(total_billed - total_received, 0)
        f1, f2, f3 = st.columns(3)
        f1.metric("Total Billed", f"₹{total_billed:,.0f}")
        f2.metric("Total Received", f"₹{total_received:,.0f}")
        f3.metric("Outstanding", f"₹{outstanding:,.0f}")
    else:
        st.info("No invoices raised yet.")

# =====================================================================
# CLIENTS  (list + Client 360 view)
# =====================================================================

elif menu == "Clients":
    st.header("📄 Clients")

    search = st.text_input("🔍 Search by Name / PAN / GSTIN / Mobile / Client ID")
    filtered = clients_df.copy()
    if search:
        filtered = filtered[
            filtered.astype(str).apply(lambda r: r.str.contains(search, case=False, na=False).any(), axis=1)
        ]
    st.dataframe(filtered, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("👤 Client 360")

    if clients_df.empty:
        st.info("No clients yet - add one from 'Add Client'.")
        st.stop()

    label_map = client_label_map()
    selected_id = st.selectbox(
        "Select client",
        options=list(label_map.keys()),
        format_func=lambda cid: label_map.get(cid, cid),
        index=None,
        placeholder="Type to search...",
    )

    if selected_id is None:
        st.info("Select a client above to view full profile, work items, invoices and history.")
        st.stop()

    row = clients_df[clients_df["Client ID"] == selected_id].iloc[0]

    with st.form("edit_client_form"):
        c1, c2, c3 = st.columns(3)
        with c1:
            name = st.text_input("Client Name", value=row.get("Client Name", ""))
            pan = st.text_input("PAN", value=row.get("PAN", ""))
            gstin = st.text_input("GSTIN", value=row.get("GSTIN", ""))
            mobile = st.text_input("Mobile", value=row.get("Mobile", ""))
        with c2:
            email = st.text_input("Email", value=row.get("Email", ""))
            client_type = st.selectbox(
                "Client Type",
                ["Individual", "Proprietorship", "Partnership", "LLP", "Company", "HUF", "Trust"],
                index=max(0, ["Individual", "Proprietorship", "Partnership", "LLP", "Company", "HUF", "Trust"].index(row.get("Client Type")) if row.get("Client Type") in ["Individual", "Proprietorship", "Partnership", "LLP", "Company", "HUF", "Trust"] else 0),
            )
            source = st.text_input("Client Source", value=row.get("Client Source", ""))
            default_assigned = st.selectbox(
                "Default Assigned To", staff_options,
                index=staff_options.index(row.get("Default Assigned To")) if row.get("Default Assigned To") in staff_options else 0,
            )
        with c3:
            folder_ref = st.text_input("Client Folder Reference", value=row.get("Client Folder Reference", ""))
            status = st.selectbox(
                "Client Status", ["Active", "Inactive", "On Hold"],
                index=["Active", "Inactive", "On Hold"].index(row.get("Client Status")) if row.get("Client Status") in ["Active", "Inactive", "On Hold"] else 0,
            )
            address = st.text_area("Address", value=row.get("Address", ""), height=68)

        if st.form_submit_button("💾 Save Profile Changes"):
            updates = {
                "Client Name": name, "PAN": pan, "GSTIN": gstin, "Mobile": mobile,
                "Email": email, "Client Type": client_type, "Client Source": source,
                "Default Assigned To": default_assigned, "Client Folder Reference": folder_ref,
                "Client Status": status, "Address": address,
            }
            for field, new_val in updates.items():
                old_val = row.get(field, "")
                if str(old_val) != str(new_val):
                    gsf.log_history(logged_user, selected_id, "", field, old_val, new_val)
            gsf.update_client(selected_id, updates)
            st.success("Profile updated.")
            st.cache_data.clear()
            st.rerun()

    st.divider()
    tab1, tab2, tab3, tab4 = st.tabs(["🗂️ Work Items", "🧾 Invoices", "💵 Payments", "📜 History"])

    with tab1:
        client_work = work_df[work_df["Client ID"] == selected_id]
        if client_work.empty:
            st.info("No work items yet for this client.")
        else:
            st.dataframe(
                client_work[["Work ID", "Service Code", "Period", "Status", "Assigned To", "Due Date", "Next Follow Up"]],
                use_container_width=True, hide_index=True,
            )

    with tab2:
        client_invoices = invoices_df[invoices_df["Client ID"] == selected_id]
        if client_invoices.empty:
            st.info("No invoices yet for this client.")
        else:
            st.dataframe(client_invoices, use_container_width=True, hide_index=True)

    with tab3:
        client_payments = payments_df[payments_df["Client ID"] == selected_id]
        if client_payments.empty:
            st.info("No payments recorded yet for this client.")
        else:
            st.dataframe(client_payments, use_container_width=True, hide_index=True)

    with tab4:
        history_df = gsf.load_history()
        client_history = history_df[history_df["Client ID"] == selected_id] if len(history_df) else history_df
        if client_history.empty:
            st.info("No history yet for this client.")
        else:
            st.dataframe(client_history.sort_values("Date", ascending=False), use_container_width=True, hide_index=True)

# =====================================================================
# ADD CLIENT
# =====================================================================

elif menu == "Add Client":
    st.header("➕ Add Client")

    with st.form("add_client_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            name = st.text_input("Client Name *")
            pan = st.text_input("PAN")
            gstin = st.text_input("GSTIN")
            mobile = st.text_input("Mobile")
            email = st.text_input("Email")
        with c2:
            client_type = st.selectbox("Client Type", ["Individual", "Proprietorship", "Partnership", "LLP", "Company", "HUF", "Trust"])
            source = st.text_input("Client Source")
            assigned = st.selectbox("Default Assigned To", staff_options)
            folder_ref = st.text_input("Client Folder Reference")
            address = st.text_area("Address", height=68)

        submitted = st.form_submit_button("Add Client")
        if submitted:
            if not name.strip():
                st.error("Client Name is required.")
            else:
                new_id = gsf.add_client({
                    "Client Name": name, "PAN": pan, "GSTIN": gstin, "Mobile": mobile,
                    "Email": email, "Client Type": client_type, "Client Source": source,
                    "Default Assigned To": assigned, "Client Folder Reference": folder_ref,
                    "Address": address,
                })
                st.success(f"Client added with ID {new_id}")
                st.cache_data.clear()

# =====================================================================
# WORK TRACKER
# =====================================================================

elif menu == "Work Tracker":
    st.header("🗂️ Work Tracker")

    label_map = client_label_map()

    f1, f2, f3 = st.columns(3)
    with f1:
        svc_filter = st.selectbox("Filter by Service", ["All"] + service_options)
    with f2:
        staff_filter = st.selectbox("Filter by Assigned To", ["All"] + staff_options)
    with f3:
        show_terminal = st.checkbox("Include completed/closed items", value=False)

    view = work_df.copy()
    if not show_terminal:
        view = view[~view["Status"].astype(str).isin(gsf.TERMINAL_STATUSES)]
    if svc_filter != "All":
        view = view[view["Service Code"] == svc_filter]
    if staff_filter != "All":
        view = view[view["Assigned To"] == staff_filter]

    view = view.copy()
    view["Client Name"] = view["Client ID"].map(lambda cid: label_map.get(cid, cid))

    st.metric("Items shown", len(view))

    if view.empty:
        st.info("No work items match this filter.")
    else:
        for status in sorted(view["Status"].dropna().unique()):
            status_rows = view[view["Status"] == status]
            st.markdown(f"#### {status} ({len(status_rows)})")
            st.dataframe(
                status_rows[["Work ID", "Client Name", "Service Code", "Period", "Assigned To", "Due Date", "Next Follow Up"]],
                use_container_width=True, hide_index=True,
            )

    st.divider()
    st.subheader("✏️ Update a Work Item")

    if work_df.empty:
        st.info("No work items to update yet.")
        st.stop()

    work_display = work_df.copy()
    work_display["label"] = work_display.apply(
        lambda r: f"{label_map.get(r['Client ID'], r['Client ID'])} | {r['Service Code']} | {r['Period']} | {r['Work ID']}",
        axis=1,
    )
    selected_label = st.selectbox("Select work item", options=work_display["label"].tolist(), index=None, placeholder="Search...")

    if selected_label:
        wrow = work_display[work_display["label"] == selected_label].iloc[0]
        status_choices = gsf.status_options_for(wrow["Service Code"], services_df)

        c1, c2 = st.columns(2)
        with c1:
            new_status = st.selectbox(
                "Status", status_choices,
                index=status_choices.index(wrow["Status"]) if wrow["Status"] in status_choices else 0,
            )
            new_assigned = st.selectbox(
                "Assigned To", staff_options,
                index=staff_options.index(wrow["Assigned To"]) if wrow["Assigned To"] in staff_options else 0,
            )
        with c2:
            current_followup = pd.to_datetime(wrow.get("Next Follow Up", ""), errors="coerce", dayfirst=True)
            current_followup = current_followup.date() if pd.notna(current_followup) else date.today()
            new_followup = st.date_input("Next Follow Up", value=current_followup)
            new_remarks = st.text_area("Brief Remarks", value=wrow.get("Brief Remarks", ""))

        if st.button("💾 Save Work Item"):
            updates = {"Status": new_status, "Assigned To": new_assigned, "Brief Remarks": new_remarks}
            if new_status in gsf.TERMINAL_STATUSES:
                updates["Next Follow Up"] = ""
                updates["Completed Date"] = date.today().strftime("%d-%m-%Y")
            else:
                updates["Next Follow Up"] = new_followup.strftime("%d-%m-%Y")

            for field, new_val in updates.items():
                old_val = wrow.get(field, "")
                if str(old_val) != str(new_val):
                    gsf.log_history(logged_user, wrow["Client ID"], wrow["Work ID"], field, old_val, new_val)

            gsf.update_work_item(wrow["Work ID"], updates)
            st.success("Work item updated.")
            st.cache_data.clear()
            st.rerun()

# =====================================================================
# ADD WORK ITEM
# =====================================================================

elif menu == "Add Work Item":
    st.header("➕ Add Work Item")

    if clients_df.empty:
        st.info("Add a client first.")
        st.stop()

    label_map = client_label_map()
    client_id = st.selectbox("Client", options=list(label_map.keys()), format_func=lambda c: label_map.get(c, c), index=None, placeholder="Search client...")
    service_code = st.selectbox("Service", options=service_options)
    period = st.text_input("Period", placeholder="e.g. FY 2026-27, or Jul-2026, or Q2 FY26-27")
    assigned = st.selectbox("Assigned To", staff_options)
    due_date = st.date_input("Due Date", value=date.today() + timedelta(days=30))

    default_status = gsf.status_options_for(service_code, services_df)[0] if service_code else "Documents Awaited"

    if st.button("Add Work Item"):
        if not client_id or not period.strip():
            st.error("Client and Period are required.")
        else:
            work_id = gsf.add_work_item({
                "Client ID": client_id, "Service Code": service_code, "Period": period,
                "Status": default_status, "Assigned To": assigned,
                "Start Date": date.today().strftime("%d-%m-%Y"),
                "Due Date": due_date.strftime("%d-%m-%Y"),
            })
            st.success(f"Work item {work_id} added.")
            st.cache_data.clear()

# =====================================================================
# BILLING - CREATE INVOICE
# =====================================================================

elif menu == "Billing":
    st.header("💰 Billing — Create Invoice")

    if clients_df.empty:
        st.info("Add a client first.")
        st.stop()

    label_map = client_label_map()
    client_id = st.selectbox("Client", options=list(label_map.keys()), format_func=lambda c: label_map.get(c, c), index=None, placeholder="Search client...")

    if not client_id:
        st.info("Select a client to raise an invoice.")
        st.stop()

    client_row = clients_df[clients_df["Client ID"] == client_id].iloc[0]
    client_work = work_df[work_df["Client ID"] == client_id]

    st.caption("Optionally link this invoice to specific work items (for your own reference — does not affect the amount automatically beyond the suggestion below).")
    work_choices = client_work.apply(lambda r: f"{r['Work ID']} | {r['Service Code']} | {r['Period']} | {r['Status']}", axis=1).tolist()
    linked = st.multiselect("Link Work Item(s)", options=work_choices)
    linked_ids = [w.split(" | ")[0] for w in linked]

    st.divider()
    st.subheader("Line Items")
    st.caption("Add one or more lines. Defaults to the service's default fee if set in Services Catalog.")

    n_lines = st.number_input("Number of line items", min_value=1, max_value=10, value=max(1, len(linked_ids)))
    line_items = []
    for i in range(int(n_lines)):
        c1, c2 = st.columns([3, 1])
        default_desc = ""
        default_amt = 0.0
        if i < len(linked_ids):
            wrow = client_work[client_work["Work ID"] == linked_ids[i]]
            if len(wrow):
                svc = wrow.iloc[0]["Service Code"]
                svc_row = services_df[services_df["Service Code"] == svc]
                svc_name = svc_row.iloc[0]["Service Name"] if len(svc_row) else svc
                default_desc = f"{svc_name} - {wrow.iloc[0]['Period']}"
                fee = pd.to_numeric(svc_row.iloc[0]["Default Fee"], errors="coerce") if len(svc_row) else None
                default_amt = float(fee) if pd.notna(fee) else 0.0
        with c1:
            desc = st.text_input(f"Description {i+1}", value=default_desc, key=f"desc_{i}")
        with c2:
            amt = st.number_input(f"Amount {i+1} (₹)", min_value=0.0, value=default_amt, step=100.0, key=f"amt_{i}")
        if desc.strip():
            line_items.append({"description": desc, "amount": amt})

    st.divider()
    gst_applicable = st.checkbox("GST Applicable on this invoice")
    gst_amount = 0.0
    if gst_applicable:
        gst_amount = st.number_input("GST Amount (₹)", min_value=0.0, step=10.0)

    remarks = st.text_area("Invoice Remarks")

    subtotal = sum(li["amount"] for li in line_items)
    total = subtotal + (gst_amount if gst_applicable else 0)
    st.metric("Invoice Total", f"₹{total:,.0f}")

    if st.button("🧾 Generate & Save Invoice", type="primary"):
        if not line_items:
            st.error("Add at least one line item with a description.")
        else:
            invoice_date = date.today().strftime("%d-%m-%Y")
            description_summary = "; ".join(li["description"] for li in line_items)
            invoice_no = gsf.add_invoice({
                "Invoice Date": invoice_date,
                "Client ID": client_id,
                "Work ID(s)": ", ".join(linked_ids),
                "Description": description_summary,
                "Amount": subtotal,
                "GST Applicable": "Yes" if gst_applicable else "No",
                "GST Amount": gst_amount if gst_applicable else 0,
                "Total": total,
                "Status": "Unpaid",
            })

            pdf_bytes = generate_invoice_pdf(
                client_row["Client Name"], invoice_no, invoice_date, line_items,
                remarks=remarks, gst_applicable=gst_applicable, gst_amount=gst_amount,
            )

            st.success(f"Invoice {invoice_no} saved.")
            st.download_button("📄 Download Invoice PDF", pdf_bytes, file_name=f"{invoice_no}.pdf", mime="application/pdf")
            st.cache_data.clear()

# =====================================================================
# RECORD PAYMENT
# =====================================================================

elif menu == "Record Payment":
    st.header("💵 Record Payment")

    open_invoices = invoices_df[invoices_df["Status"] != "Paid"].copy() if len(invoices_df) else invoices_df

    if open_invoices.empty:
        st.info("No unpaid or partially paid invoices.")
        st.stop()

    label_map = client_label_map()
    open_invoices["label"] = open_invoices.apply(
        lambda r: f"{r['Invoice No']} | {label_map.get(r['Client ID'], r['Client ID'])} | Total ₹{r['Total']}",
        axis=1,
    )
    selected_label = st.selectbox("Select Invoice", options=open_invoices["label"].tolist(), index=None, placeholder="Search invoice...")

    if not selected_label:
        st.stop()

    inv_row = open_invoices[open_invoices["label"] == selected_label].iloc[0]
    due, paid_so_far, total = invoice_due_amount(inv_row, payments_df)

    c1, c2, c3 = st.columns(3)
    c1.metric("Invoice Total", f"₹{total:,.0f}")
    c2.metric("Paid So Far", f"₹{paid_so_far:,.0f}")
    c3.metric("Due", f"₹{due:,.0f}")

    st.divider()
    amount = st.number_input("Amount Received (₹)", min_value=0.0, max_value=float(due) if due > 0 else None, step=100.0)
    mode = st.selectbox("Payment Mode", ["Cash", "UPI", "Bank Transfer", "Cheque"])
    remarks = st.text_area("Remarks")

    if st.button("💾 Save Payment", type="primary"):
        if amount <= 0:
            st.error("Enter an amount greater than zero.")
        else:
            gsf.add_payment({
                "Client ID": inv_row["Client ID"],
                "Invoice No": inv_row["Invoice No"],
                "Amount": amount,
                "Mode": mode,
                "Received By": logged_user,
                "Remarks": remarks,
            })
            new_paid = paid_so_far + amount
            new_status = "Paid" if new_paid >= total else "Partial"
            gsf.update_invoice(inv_row["Invoice No"], {"Status": new_status})
            st.success(f"Payment recorded. Invoice status: {new_status}")
            st.cache_data.clear()
            st.rerun()

# =====================================================================
# FEE RECOVERY / AGING
# =====================================================================

elif menu == "Fee Recovery / Aging":
    st.header("💰 Fee Recovery / Aging Report")

    if invoices_df.empty:
        st.info("No invoices raised yet.")
        st.stop()

    label_map = client_label_map()
    inv = invoices_df.copy()
    inv["Client Name"] = inv["Client ID"].map(lambda cid: label_map.get(cid, cid))

    rows = []
    for _, r in inv.iterrows():
        due, paid, total = invoice_due_amount(r, payments_df)
        if due <= 0:
            continue
        inv_date = pd.to_datetime(r.get("Invoice Date", ""), errors="coerce", dayfirst=True)
        age_days = (pd.Timestamp.today() - inv_date).days if pd.notna(inv_date) else None
        if age_days is None:
            bucket = "Unknown"
        elif age_days <= 30:
            bucket = "0-30 days"
        elif age_days <= 60:
            bucket = "31-60 days"
        elif age_days <= 90:
            bucket = "61-90 days"
        else:
            bucket = "90+ days"
        rows.append({
            "Invoice No": r["Invoice No"], "Client Name": r["Client Name"],
            "Invoice Date": r["Invoice Date"], "Total": total, "Paid": paid,
            "Due": due, "Aging Bucket": bucket,
        })

    aging_df = pd.DataFrame(rows)

    if aging_df.empty:
        st.success("No outstanding invoices. 🎉")
        st.stop()

    c1, c2 = st.columns(2)
    c1.metric("Invoices with Balance Due", len(aging_df))
    c2.metric("Total Outstanding", f"₹{aging_df['Due'].sum():,.0f}")

    st.divider()
    st.subheader("By Aging Bucket")
    bucket_summary = aging_df.groupby("Aging Bucket")["Due"].sum().reindex(
        ["0-30 days", "31-60 days", "61-90 days", "90+ days", "Unknown"]
    ).dropna().reset_index()
    st.dataframe(bucket_summary, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Outstanding Invoices")
    st.dataframe(aging_df.sort_values("Due", ascending=False), use_container_width=True, hide_index=True)

# =====================================================================
# FOLLOW-UPS
# =====================================================================

elif menu == "Follow-Ups":
    st.header("📞 Follow-Ups")

    label_map = client_label_map()
    temp = work_df.copy()
    temp["Next Follow Up_dt"] = pd.to_datetime(temp["Next Follow Up"], errors="coerce", dayfirst=True)

    due = temp[
        temp["Next Follow Up_dt"].notna()
        & (temp["Next Follow Up_dt"].dt.date <= date.today())
        & (~temp["Status"].astype(str).isin(gsf.TERMINAL_STATUSES))
    ].copy()

    st.metric("Due Follow-Ups", len(due))

    if due.empty:
        st.info("No follow-ups due today.")
        st.stop()

    due["Client Name"] = due["Client ID"].map(lambda cid: label_map.get(cid, cid))
    st.dataframe(
        due[["Work ID", "Client Name", "Service Code", "Status", "Assigned To", "Next Follow Up"]],
        use_container_width=True, hide_index=True,
    )

    due["label"] = due.apply(lambda r: f"{r['Client Name']} | {r['Service Code']} | {r['Work ID']}", axis=1)
    selected_label = st.selectbox("Select item", options=due["label"].tolist())
    selected_work_id = selected_label.split("|")[-1].strip()

    c1, c2 = st.columns(2)
    with c1:
        if st.button("🗑️ Remove Follow-Up"):
            gsf.update_work_item(selected_work_id, {"Next Follow Up": ""})
            st.success("Follow-up cleared.")
            st.cache_data.clear()
            st.rerun()
    with c2:
        if st.button("⏰ Snooze 7 Days"):
            new_date = (date.today() + timedelta(days=7)).strftime("%d-%m-%Y")
            gsf.update_work_item(selected_work_id, {"Next Follow Up": new_date})
            st.success(f"Snoozed to {new_date}.")
            st.cache_data.clear()
            st.rerun()

# =====================================================================
# SERVICES CATALOG
# =====================================================================

elif menu == "Services Catalog":
    st.header("🧾 Services Catalog")
    st.caption("Add a new service here (e.g. a new GST return type) — it becomes selectable everywhere immediately, no code changes needed.")

    st.dataframe(services_df, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("➕ Add Service")
    with st.form("add_service_form", clear_on_submit=True):
        code = st.text_input("Service Code (short, unique, e.g. GST-MON)")
        name = st.text_input("Service Name")
        freq = st.selectbox("Frequency", ["Annual", "Quarterly", "Monthly", "One-time"])
        fee = st.number_input("Default Fee (₹)", min_value=0.0, step=100.0)
        status_opts = st.text_input("Status Options (comma separated)", value=",".join(gsf.DEFAULT_STATUS_OPTIONS))
        if st.form_submit_button("Add Service"):
            if not code.strip() or not name.strip():
                st.error("Service Code and Name are required.")
            else:
                gsf.add_service({
                    "Service Code": code.strip(), "Service Name": name.strip(),
                    "Frequency": freq, "Default Fee": fee, "Status Options": status_opts,
                })
                st.success("Service added.")
                st.cache_data.clear()

# =====================================================================
# STAFF
# =====================================================================

elif menu == "Staff":
    st.header("👥 Staff")
    st.dataframe(staff_df, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("➕ Add Staff")
    with st.form("add_staff_form", clear_on_submit=True):
        name = st.text_input("Staff Name")
        role = st.selectbox("Role", ["Admin", "Staff"])
        if st.form_submit_button("Add Staff"):
            if not name.strip():
                st.error("Name required.")
            else:
                gsf.add_staff(name.strip(), role)
                st.success("Staff added. Remember to also add their login under st.secrets['users'].")
                st.cache_data.clear()

# =====================================================================
# UPDATE HISTORY
# =====================================================================

elif menu == "Update History":
    st.header("📜 Update History")
    history_df = gsf.load_history()
    if history_df.empty:
        st.info("No history yet.")
    else:
        st.dataframe(history_df.sort_values("Date", ascending=False), use_container_width=True, hide_index=True)
