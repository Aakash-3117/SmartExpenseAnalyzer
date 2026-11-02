
from flask import Flask, render_template, request, redirect, url_for
import sqlite3
from datetime import date

app = Flask(__name__)
DATABASE = "expenses.db"


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def create_table():
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            amount REAL NOT NULL,
            category TEXT NOT NULL
        )
    """)

    columns = [
        row["name"]
        for row in conn.execute("PRAGMA table_info(expenses)").fetchall()
    ]

    if "expense_date" not in columns:
        conn.execute("ALTER TABLE expenses ADD COLUMN expense_date TEXT")

    conn.execute(
        "UPDATE expenses SET expense_date = ? "
        "WHERE expense_date IS NULL OR expense_date = ''",
        (date.today().isoformat(),)
    )

    # New table for monthly budgets
    conn.execute("""
        CREATE TABLE IF NOT EXISTS budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            month TEXT UNIQUE NOT NULL,
            amount REAL NOT NULL
        )
    """)

    conn.commit()
    conn.close()


@app.route("/", methods=["GET", "POST"])
def home():
    conn = get_db()

    if request.method == "POST":
        name = request.form["expense_name"].strip()
        amount = float(request.form["amount"])
        category = request.form["category"]
        expense_date = request.form.get("expense_date") or date.today().isoformat()

        if name and amount > 0:
            conn.execute("""
                INSERT INTO expenses
                (name, amount, category, expense_date)
                VALUES (?, ?, ?, ?)
            """, (name, amount, category, expense_date))
            conn.commit()

        conn.close()
        return redirect(url_for("home", month=expense_date[:7]))

    selected_month = request.args.get("month", "all")

    months = conn.execute("""
        SELECT DISTINCT substr(expense_date, 1, 7) AS month
        FROM expenses
        ORDER BY month DESC
    """).fetchall()

    monthly_totals = conn.execute("""
        SELECT substr(expense_date, 1, 7) AS month,
               SUM(amount) AS total
        FROM expenses
        GROUP BY substr(expense_date, 1, 7)
        ORDER BY month DESC
    """).fetchall()

    if selected_month == "all":
        expenses = conn.execute(
            "SELECT * FROM expenses ORDER BY id DESC"
        ).fetchall()
    else:
        expenses = conn.execute("""
            SELECT * FROM expenses
            WHERE substr(expense_date, 1, 7) = ?
            ORDER BY id DESC
        """, (selected_month,)).fetchall()

    total_expenses = sum(item["amount"] for item in expenses)

    if selected_month == "all":
        category_totals = conn.execute("""
            SELECT category, SUM(amount) AS total
            FROM expenses
            GROUP BY category
            ORDER BY total DESC
        """).fetchall()
    else:
        category_totals = conn.execute("""
            SELECT category, SUM(amount) AS total
            FROM expenses
            WHERE substr(expense_date, 1, 7) = ?
            GROUP BY category
            ORDER BY total DESC
        """, (selected_month,)).fetchall()

    if category_totals and total_expenses > 0:
        highest_category = category_totals[0]["category"]
        highest_amount = category_totals[0]["total"]
        percentage = highest_amount / total_expenses * 100

        insight = (
            f"Your highest spending category is {highest_category} "
            f"(₹{highest_amount:.2f}). It accounts for "
            f"{percentage:.1f}% of your total spending."
        )
    else:
        insight = "No expenses available for this month."

    # Get budget for the selected month
    monthly_budget = 0

    if selected_month != "all":
        budget_row = conn.execute(
            "SELECT amount FROM budgets WHERE month = ?",
            (selected_month,)
        ).fetchone()

        if budget_row:
            monthly_budget = budget_row["amount"]

    remaining_budget = monthly_budget - total_expenses
    budget_message = ""

    if monthly_budget > 0:
        if remaining_budget >= 0:
            budget_message = (
                f"You have ₹{remaining_budget:.2f} left in your budget."
            )
        else:
            budget_message = (
                f"Warning! You exceeded your budget by "
                f"₹{abs(remaining_budget):.2f}."
            )

    conn.close()

    return render_template(
        "index.html",
        expenses=expenses,
        total_expenses=total_expenses,
        category_totals=category_totals,
        insight=insight,
        monthly_totals=monthly_totals,
        months=months,
        selected_month=selected_month,
        today=date.today().isoformat(),
        monthly_budget=monthly_budget,
        remaining_budget=remaining_budget,
        budget_message=budget_message
    )


@app.route("/set-budget", methods=["POST"])
def set_budget():
    month = request.form.get("month")
    amount = float(request.form.get("budget", 0))

    if month and amount > 0:
        conn = get_db()
        conn.execute("""
            INSERT INTO budgets (month, amount)
            VALUES (?, ?)
            ON CONFLICT(month) DO UPDATE SET amount = excluded.amount
        """, (month, amount))
        conn.commit()
        conn.close()

    return redirect(url_for("home", month=month))


@app.route("/delete/<int:index>", methods=["POST"])
def delete_expense(index):
    month = request.form.get("month", "all")

    conn = get_db()
    conn.execute("DELETE FROM expenses WHERE id = ?", (index,))
    conn.commit()
    conn.close()

    return redirect(url_for("home", month=month))


if __name__ == "__main__":
    create_table()
    app.run(debug=True)
