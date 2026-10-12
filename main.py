import csv
import sqlite3
import hashlib
import secrets
import hmac
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import date, datetime
from pathlib import Path

from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

DB = Path(__file__).resolve().parent / "expenses.db"
CATEGORIES = ["Food", "Travel", "Shopping", "Education", "Bills", "Health",
              "Entertainment", "Salary", "Freelance", "Other"]


def connect_db():
    return sqlite3.connect(DB)


def initialize_db():
    # Creates missing tables and keeps existing transactions/settings.
    with connect_db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS transactions(
            id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL,
            amount REAL NOT NULL, category TEXT NOT NULL,
            txn_date TEXT NOT NULL, description TEXT)""")
        con.execute("""CREATE TABLE IF NOT EXISTS budgets(
            month TEXT PRIMARY KEY, amount REAL NOT NULL)""")
        con.execute("""CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY, value TEXT NOT NULL)""")


def get_setting(key):
    with connect_db() as con:
        row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def set_setting(key, value):
    with connect_db() as con:
        con.execute("""INSERT INTO settings(key,value) VALUES(?,?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value""", (key, value))


def make_hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200000).hex()


def password_login(root):
    first_time = get_setting("password_hash") is None
    win = tk.Toplevel(root)
    win.title("Expense Tracker Login")
    win.geometry("390x280")
    win.resizable(False, False)
    win.grab_set()
    ttk.Label(win, text="Create Password" if first_time else "Welcome Back",
              font=("Segoe UI", 17, "bold")).pack(pady=(20, 12))
    ttk.Label(win, text="Password (minimum 6 characters)").pack()
    password = tk.StringVar()
    ttk.Entry(win, textvariable=password, show="*", width=30).pack(pady=7)
    confirm = tk.StringVar()
    if first_time:
        ttk.Label(win, text="Confirm Password").pack()
        ttk.Entry(win, textvariable=confirm, show="*", width=30).pack(pady=7)
    result = {"ok": False}

    def submit():
        value = password.get()
        if first_time:
            if len(value) < 6:
                messagebox.showerror("Password", "Use at least 6 characters.", parent=win)
                return
            if value != confirm.get():
                messagebox.showerror("Password", "Passwords do not match.", parent=win)
                return
            salt = secrets.token_hex(16)
            set_setting("password_salt", salt)
            set_setting("password_hash", make_hash(value, salt))
            result["ok"] = True
            messagebox.showinfo("Success", "Password created. Remember it.", parent=win)
            win.destroy()
        else:
            salt, expected = get_setting("password_salt"), get_setting("password_hash")
            if salt and expected and hmac.compare_digest(make_hash(value, salt), expected):
                result["ok"] = True
                win.destroy()
            else:
                messagebox.showerror("Login Failed", "Incorrect password.", parent=win)

    ttk.Button(win, text="Continue", command=submit).pack(pady=12)
    win.protocol("WM_DELETE_WINDOW", root.destroy)
    root.wait_window(win)
    return result["ok"]


class ExpenseTracker:
    def __init__(self, root):
        self.root = root
        root.withdraw()
        root.title("Expense Tracker | Personal Finance Manager")
        root.geometry("1200x780")
        root.minsize(950, 650)
        self.month = tk.StringVar(value=date.today().strftime("%Y-%m"))
        self.search = tk.StringVar()
        self.type_filter = tk.StringVar(value="All")
        self.category_filter = tk.StringVar(value="All")
        self.edit_id = None
        self.setup_style()
        if not password_login(root):
            root.destroy()
            return
        self.create_header()
        self.create_tabs()
        self.refresh_all()
        root.deiconify()

    def setup_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Treeview", rowheight=27, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
        style.configure("TButton", padding=6)
        style.configure("Title.TLabel", font=("Segoe UI", 20, "bold"))
        style.configure("Value.TLabel", font=("Segoe UI", 16, "bold"))

    def create_header(self):
        header = ttk.Frame(self.root, padding=12)
        header.pack(fill="x")
        ttk.Label(header, text="EXPENSE TRACKER", style="Title.TLabel").pack(side="left")
        right = ttk.Frame(header)
        right.pack(side="right")
        ttk.Label(right, text="Month (YYYY-MM)").pack(side="left", padx=4)
        ttk.Entry(right, textvariable=self.month, width=10).pack(side="left", padx=4)
        ttk.Button(right, text="Load Month", command=self.change_month).pack(side="left")

    def create_tabs(self):
        self.tabs = ttk.Notebook(self.root)
        self.tabs.pack(fill="both", expand=True, padx=12, pady=8)
        self.dashboard = ttk.Frame(self.tabs, padding=12)
        self.transactions = ttk.Frame(self.tabs, padding=12)
        self.budget_tab = ttk.Frame(self.tabs, padding=12)
        self.reports_tab = ttk.Frame(self.tabs, padding=12)
        self.tabs.add(self.dashboard, text="Dashboard")
        self.tabs.add(self.transactions, text="Transactions")
        self.tabs.add(self.budget_tab, text="Budget & Charts")
        self.tabs.add(self.reports_tab, text="Monthly Reports")
        self.build_dashboard()
        self.build_transactions()
        self.build_budget()
        self.build_reports()

    # Dashboard
    def card(self, parent, title, col):
        box = ttk.LabelFrame(parent, text=title, padding=12)
        box.grid(row=0, column=col, sticky="nsew", padx=5)
        parent.columnconfigure(col, weight=1)
        label = ttk.Label(box, text="Rs. 0.00", style="Value.TLabel")
        label.pack(anchor="w")
        return label

    def build_dashboard(self):
        ttk.Label(self.dashboard, text="Monthly Financial Summary",
                  style="Title.TLabel").pack(anchor="w", pady=(0, 12))
        cards = ttk.Frame(self.dashboard)
        cards.pack(fill="x")
        self.income_label = self.card(cards, "Total Income", 0)
        self.expense_label = self.card(cards, "Total Expenses", 1)
        self.balance_label = self.card(cards, "Net Balance", 2)
        ttk.Label(self.dashboard, text="Recent Transactions",
                  font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(20, 8))
        cols = ("date", "type", "category", "amount", "description")
        self.recent = ttk.Treeview(self.dashboard, columns=cols, show="headings", height=10)
        for col, title in zip(cols, ["Date", "Type", "Category", "Amount (Rs.)", "Description"]):
            self.recent.heading(col, text=title)
            self.recent.column(col, width=150)
        self.recent.column("description", width=260)
        self.recent.pack(fill="both", expand=True)

    # Transactions
    def build_transactions(self):
        form = ttk.LabelFrame(self.transactions, text="Add / Edit Transaction", padding=9)
        form.pack(fill="x", pady=(0, 8))
        self.tx_type = tk.StringVar(value="Expense")
        self.amount = tk.StringVar()
        self.category = tk.StringVar(value="Food")
        self.tx_date = tk.StringVar(value=date.today().isoformat())
        self.description = tk.StringVar()
        fields = [
            ("Type", self.tx_type, ["Expense", "Income"]),
            ("Amount", self.amount, None),
            ("Category", self.category, CATEGORIES),
            ("Date YYYY-MM-DD", self.tx_date, None),
            ("Description", self.description, None)]
        for col, (title, variable, choices) in enumerate(fields):
            ttk.Label(form, text=title).grid(row=0, column=col, sticky="w", padx=4)
            if choices:
                widget = ttk.Combobox(form, textvariable=variable, values=choices, width=15,
                                      state="readonly" if title == "Type" else "normal")
            else:
                widget = ttk.Entry(form, textvariable=variable, width=19)
            widget.grid(row=1, column=col, padx=4, pady=4)
        self.save_btn = ttk.Button(form, text="Add Transaction", command=self.save_transaction)
        self.save_btn.grid(row=2, column=0, padx=4, pady=6, sticky="w")
        ttk.Button(form, text="Clear Form", command=self.clear_form).grid(
            row=2, column=1, padx=4, pady=6, sticky="w")

        filters = ttk.LabelFrame(self.transactions, text="Search & Filter", padding=8)
        filters.pack(fill="x", pady=(0, 8))
        ttk.Label(filters, text="Search").grid(row=0, column=0, padx=4)
        search_box = ttk.Entry(filters, textvariable=self.search, width=20)
        search_box.grid(row=1, column=0, padx=4, pady=3)
        search_box.bind("<KeyRelease>", lambda _e: self.refresh_table())
        ttk.Label(filters, text="Type").grid(row=0, column=1, padx=4)
        type_box = ttk.Combobox(filters, textvariable=self.type_filter,
                                values=["All", "Expense", "Income"], state="readonly", width=12)
        type_box.grid(row=1, column=1, padx=4, pady=3)
        type_box.bind("<<ComboboxSelected>>", lambda _e: self.refresh_table())
        ttk.Label(filters, text="Category").grid(row=0, column=2, padx=4)
        cat_box = ttk.Combobox(filters, textvariable=self.category_filter,
                               values=["All"] + CATEGORIES, width=15, state="readonly")
        cat_box.grid(row=1, column=2, padx=4, pady=3)
        cat_box.bind("<<ComboboxSelected>>", lambda _e: self.refresh_table())
        ttk.Button(filters, text="Clear Filters", command=self.clear_filters).grid(row=1, column=3, padx=5)
        ttk.Button(filters, text="Export CSV", command=self.export_csv).grid(row=1, column=4, padx=5)

        cols = ("id", "date", "type", "category", "amount", "description")
        self.table = ttk.Treeview(self.transactions, columns=cols, show="headings")
        for col, title in zip(cols, ["ID", "Date", "Type", "Category", "Amount (Rs.)", "Description"]):
            self.table.heading(col, text=title)
            self.table.column(col, width=125)
        self.table.column("id", width=45)
        self.table.column("description", width=220)
        scroll = ttk.Scrollbar(self.transactions, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        self.table.pack(side="left", fill="both", expand=True)
        scroll.pack(side="left", fill="y")
        buttons = ttk.Frame(self.transactions)
        buttons.pack(side="bottom", fill="x", pady=8)
        ttk.Button(buttons, text="Load Selected to Edit", command=self.load_selected).pack(side="left")
        ttk.Button(buttons, text="Delete Selected", command=self.delete_transaction).pack(side="right")

    def save_transaction(self):
        try:
            amount = float(self.amount.get().strip())
            if amount <= 0:
                raise ValueError
            tx_date = datetime.strptime(self.tx_date.get().strip(), "%Y-%m-%d").date().isoformat()
            category = self.category.get().strip()
            if not category:
                messagebox.showwarning("Input", "Enter a category.")
                return
            values = (self.tx_type.get(), amount, category, tx_date, self.description.get().strip())
            with connect_db() as con:
                if self.edit_id is None:
                    con.execute("""INSERT INTO transactions(type,amount,category,txn_date,description)
                                   VALUES(?,?,?,?,?)""", values)
                    msg = "Transaction added successfully."
                else:
                    con.execute("""UPDATE transactions SET type=?,amount=?,category=?,txn_date=?,description=?
                                   WHERE id=?""", values + (self.edit_id,))
                    msg = "Transaction updated successfully."
            self.clear_form()
            self.refresh_all()
            messagebox.showinfo("Success", msg)
        except ValueError:
            messagebox.showerror("Invalid Input", "Enter a positive amount and a valid YYYY-MM-DD date.")
        except sqlite3.Error as error:
            messagebox.showerror("Database Error", str(error))

    def load_selected(self):
        selected = self.table.selection()
        if not selected:
            messagebox.showwarning("Select", "Select a transaction first.")
            return
        tx_id = int(self.table.item(selected[0], "values")[0])
        with connect_db() as con:
            row = con.execute("""SELECT type,amount,category,txn_date,description
                                 FROM transactions WHERE id=?""", (tx_id,)).fetchone()
        if row:
            self.edit_id = tx_id
            self.tx_type.set(row[0])
            self.amount.set(str(row[1]))
            self.category.set(row[2])
            self.tx_date.set(row[3])
            self.description.set(row[4] or "")
            self.save_btn.config(text="Update Transaction")
            self.tabs.select(self.transactions)

    def clear_form(self):
        self.edit_id = None
        self.tx_type.set("Expense")
        self.amount.set("")
        self.category.set("Food")
        self.tx_date.set(date.today().isoformat())
        self.description.set("")
        self.save_btn.config(text="Add Transaction")

    def get_month_rows(self):
        with connect_db() as con:
            return con.execute("""SELECT id,type,amount,category,txn_date,description
                                  FROM transactions WHERE substr(txn_date,1,7)=?
                                  ORDER BY txn_date DESC,id DESC""",
                               (self.month.get().strip(),)).fetchall()

    def get_filtered_rows(self):
        query = """SELECT id,type,amount,category,txn_date,description
                   FROM transactions WHERE substr(txn_date,1,7)=?"""
        params = [self.month.get().strip()]
        if self.type_filter.get() != "All":
            query += " AND type=?"
            params.append(self.type_filter.get())
        if self.category_filter.get() != "All":
            query += " AND category=?"
            params.append(self.category_filter.get())
        term = self.search.get().strip().lower()
        if term:
            query += """ AND (LOWER(category) LIKE ? OR LOWER(COALESCE(description,'')) LIKE ?
                         OR CAST(amount AS TEXT) LIKE ? OR txn_date LIKE ?)"""
            params.extend([f"%{term}%"] * 4)
        query += " ORDER BY txn_date DESC,id DESC"
        with connect_db() as con:
            return con.execute(query, params).fetchall()

    def refresh_table(self):
        for item in self.table.get_children():
            self.table.delete(item)
        for row in self.get_filtered_rows():
            self.table.insert("", "end", values=(row[0], row[4], row[1], row[3],
                                                  f"{row[2]:,.2f}", row[5] or ""))

    def clear_filters(self):
        self.search.set("")
        self.type_filter.set("All")
        self.category_filter.set("All")
        self.refresh_table()

    def delete_transaction(self):
        selected = self.table.selection()
        if not selected:
            messagebox.showwarning("Select", "Select a transaction first.")
            return
        tx_id = int(self.table.item(selected[0], "values")[0])
        if not messagebox.askyesno("Confirm", "Delete this transaction permanently?"):
            return
        with connect_db() as con:
            con.execute("DELETE FROM transactions WHERE id=?", (tx_id,))
        if self.edit_id == tx_id:
            self.clear_form()
        self.refresh_all()

    def export_csv(self):
        rows = self.get_filtered_rows()
        if not rows:
            messagebox.showwarning("No Data", "No matching transactions.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv",
            initialfile=f"transactions_{self.month.get()}.csv",
            filetypes=[("CSV files", "*.csv")])
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as file:
                writer = csv.writer(file)
                writer.writerow(["ID", "Type", "Amount", "Category", "Date", "Description"])
                writer.writerows(rows)
            messagebox.showinfo("Exported", f"CSV saved to:\n{path}")
        except OSError as error:
            messagebox.showerror("Export Error", str(error))

    # Budget and charts
    def build_budget(self):
        ttk.Label(self.budget_tab, text="Monthly Budget & Analytics",
                  style="Title.TLabel").pack(anchor="w", pady=(0, 12))
        form = ttk.LabelFrame(self.budget_tab, text="Monthly Expense Limit", padding=10)
        form.pack(fill="x", pady=8)
        ttk.Label(form, text="Budget (Rs.)").pack(side="left", padx=5)
        self.budget = tk.StringVar()
        ttk.Entry(form, textvariable=self.budget, width=18).pack(side="left", padx=5)
        ttk.Button(form, text="Save Budget", command=self.save_budget).pack(side="left", padx=5)
        self.budget_status = ttk.Label(self.budget_tab, text="")
        self.budget_status.pack(anchor="w", pady=5)
        self.progress = ttk.Progressbar(self.budget_tab, maximum=100, mode="determinate")
        self.progress.pack(fill="x", pady=8)
        self.figure = Figure(figsize=(9, 4.5), dpi=100)
        self.pie_ax = self.figure.add_subplot(121)
        self.bar_ax = self.figure.add_subplot(122)
        self.canvas = FigureCanvasTkAgg(self.figure, master=self.budget_tab)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

    def get_budget(self):
        with connect_db() as con:
            row = con.execute("SELECT amount FROM budgets WHERE month=?",
                              (self.month.get().strip(),)).fetchone()
        return float(row[0]) if row else 0.0

    def save_budget(self):
        try:
            amount = float(self.budget.get().strip())
            if amount < 0:
                raise ValueError
            with connect_db() as con:
                con.execute("""INSERT INTO budgets(month,amount) VALUES(?,?)
                               ON CONFLICT(month) DO UPDATE SET amount=excluded.amount""",
                            (self.month.get().strip(), amount))
            self.refresh_budget()
            messagebox.showinfo("Saved", "Monthly budget saved.")
        except ValueError:
            messagebox.showerror("Invalid Budget", "Enter a valid non-negative budget.")

    def refresh_budget(self):
        with connect_db() as con:
            rows = con.execute("""SELECT type,category,SUM(amount) FROM transactions
                                  WHERE substr(txn_date,1,7)=? GROUP BY type,category""",
                               (self.month.get().strip(),)).fetchall()
        category_totals, income, expenses = {}, 0.0, 0.0
        for tx_type, category, total in rows:
            total = float(total or 0)
            if tx_type == "Income":
                income += total
            else:
                expenses += total
                category_totals[category] = category_totals.get(category, 0) + total
        budget = self.get_budget()
        remaining = budget - expenses
        used = expenses / budget * 100 if budget > 0 else 0
        self.budget.set(f"{budget:.2f}")
        if budget > 0:
            self.budget_status.config(text=f"Spent Rs. {expenses:,.2f} of Rs. {budget:,.2f}. "
                f"Remaining: Rs. {remaining:,.2f} ({used:.1f}% used)")
        else:
            self.budget_status.config(text=f"Spent Rs. {expenses:,.2f}. Set a monthly budget to track progress.")
        self.progress["value"] = min(used, 100)
        self.pie_ax.clear()
        self.bar_ax.clear()
        if category_totals and sum(category_totals.values()) > 0:
            self.pie_ax.pie(list(category_totals.values()), labels=list(category_totals.keys()),
                            autopct="%1.1f%%", startangle=90)
        else:
            self.pie_ax.text(0.5, 0.5, "No expenses yet", ha="center", va="center")
        self.pie_ax.set_title("Expenses by Category")
        self.bar_ax.bar(["Income", "Expenses"], [income, expenses])
        self.bar_ax.set_title("Monthly Comparison")
        self.bar_ax.set_ylabel("Amount (Rs.)")
        self.figure.tight_layout()
        self.canvas.draw_idle()

    # Monthly reports and PDF export
    def build_reports(self):
        top = ttk.Frame(self.reports_tab)
        top.pack(fill="x")
        ttk.Label(top, text="Monthly Reports", style="Title.TLabel").pack(side="left")
        ttk.Button(top, text="Refresh Reports", command=self.refresh_reports).pack(side="right", padx=4)
        ttk.Button(top, text="Export Monthly PDF", command=self.export_pdf).pack(side="right", padx=4)
        ttk.Label(self.reports_tab, text="Income, expenses and net balance for each month.").pack(
            anchor="w", pady=(10, 12))
        cols = ("month", "income", "expenses", "balance")
        self.report_tree = ttk.Treeview(self.reports_tab, columns=cols, show="headings", height=18)
        for col, title in zip(cols, ["Month", "Income (Rs.)", "Expenses (Rs.)", "Net Balance (Rs.)"]):
            self.report_tree.heading(col, text=title)
            self.report_tree.column(col, width=220, anchor="center")
        self.report_tree.pack(fill="both", expand=True)

    def monthly_summary(self):
        with connect_db() as con:
            return con.execute("""SELECT substr(txn_date,1,7),
                SUM(CASE WHEN type='Income' THEN amount ELSE 0 END),
                SUM(CASE WHEN type='Expense' THEN amount ELSE 0 END)
                FROM transactions GROUP BY substr(txn_date,1,7)
                ORDER BY substr(txn_date,1,7) DESC""").fetchall()

    def refresh_reports(self):
        for item in self.report_tree.get_children():
            self.report_tree.delete(item)
        for month, income, expenses in self.monthly_summary():
            income, expenses = income or 0, expenses or 0
            self.report_tree.insert("", "end", values=(month, f"{income:,.2f}",
                f"{expenses:,.2f}", f"{income-expenses:,.2f}"))

    def export_pdf(self):
        month = self.month.get().strip()
        try:
            datetime.strptime(month, "%Y-%m")
        except ValueError:
            messagebox.showerror("Invalid Month", "Month format must be YYYY-MM.")
            return
        rows = self.get_month_rows()
        income = sum(r[2] for r in rows if r[1] == "Income")
        expenses = sum(r[2] for r in rows if r[1] == "Expense")
        budget = self.get_budget()
        path = filedialog.asksaveasfilename(title="Save Monthly Report PDF",
            defaultextension=".pdf", initialfile=f"expense_report_{month}.pdf",
            filetypes=[("PDF files", "*.pdf")])
        if not path:
            return
        try:
            doc = SimpleDocTemplate(path, pagesize=landscape(A4),
                rightMargin=25, leftMargin=25, topMargin=28, bottomMargin=28)
            styles = getSampleStyleSheet()
            story = [Paragraph("Expense Tracker - Monthly Financial Report", styles["Title"]),
                     Spacer(1, 8), Paragraph(f"Report month: {month}", styles["Heading2"]),
                     Spacer(1, 8),
                     Paragraph(f"Total income: Rs. {income:,.2f} &nbsp;&nbsp; "
                               f"Total expenses: Rs. {expenses:,.2f} &nbsp;&nbsp; "
                               f"Net balance: Rs. {income-expenses:,.2f}", styles["Normal"]),
                     Spacer(1, 8)]
            if budget > 0:
                story += [Paragraph(f"Monthly budget: Rs. {budget:,.2f} &nbsp;&nbsp; "
                                    f"Budget remaining: Rs. {budget-expenses:,.2f}", styles["Normal"]),
                          Spacer(1, 8)]
            data = [["ID", "Date", "Type", "Category", "Amount (Rs.)", "Description"]]
            for r in rows:
                data.append([str(r[0]), r[4], r[1], r[3], f"{r[2]:,.2f}", (r[5] or "")[:80]])
            if len(data) == 1:
                data.append(["-", "-", "-", "No transactions", "0.00", "-"])
            table = Table(data, repeatRows=1, colWidths=[40, 80, 70, 95, 95, 300])
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#243b64")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f3f8")]),
                ("ALIGN", (0, 0), (4, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
            story.append(table)
            doc.build(story)
            messagebox.showinfo("PDF Exported", f"Monthly report saved to:\n{path}")
        except Exception as error:
            messagebox.showerror("PDF Export Error", str(error))

    # Refresh functions
    def change_month(self):
        month = self.month.get().strip()
        try:
            datetime.strptime(month, "%Y-%m")
        except ValueError:
            messagebox.showerror("Invalid Month", "Enter YYYY-MM, e.g. 2026-10.")
            return
        self.refresh_all()

    def refresh_dashboard(self):
        rows = self.get_month_rows()
        income = sum(r[2] for r in rows if r[1] == "Income")
        expenses = sum(r[2] for r in rows if r[1] == "Expense")
        self.income_label.config(text=f"Rs. {income:,.2f}")
        self.expense_label.config(text=f"Rs. {expenses:,.2f}")
        self.balance_label.config(text=f"Rs. {income-expenses:,.2f}")
        for item in self.recent.get_children():
            self.recent.delete(item)
        for r in rows[:12]:
            self.recent.insert("", "end", values=(r[4], r[1], r[3], f"{r[2]:,.2f}", r[5] or ""))

    def refresh_all(self):
        self.refresh_dashboard()
        self.refresh_table()
        self.refresh_budget()
        self.refresh_reports()


if __name__ == "__main__":
    initialize_db()
    root = tk.Tk()
    app = ExpenseTracker(root)
    root.mainloop()
