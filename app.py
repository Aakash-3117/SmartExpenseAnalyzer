
import os
import sqlite3
from datetime import date
from functools import wraps

from flask import (
    Flask, render_template, request,
    redirect, url_for, flash
)
from flask_login import (
    LoginManager, UserMixin, login_user,
    logout_user, login_required, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash


app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY", "change-this-secret-key-before-deployment"
)

DATABASE = "expenses.db"

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


# User account model
class User(UserMixin):
    def __init__(self, user_id, username, role, password):
        self.id = user_id
        self.username = username
        self.role = role
        self.password = password

@login_manager.user_loader
def load_user(user_id):
    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    conn.close()

    if user:
       return User(
           user["id"],
           user["username"],
           user["role"],
           user["password"]
       )
    return None


# Only the owner can access owner pages
def owner_required(function):
    @wraps(function)
    @login_required
    def wrapper(*args, **kwargs):
        if current_user.role != "owner":
            flash("Owner access only.")
            return redirect(url_for("home"))
        return function(*args, **kwargs)
    return wrapper


# Create and update database tables
def create_table():
    conn = get_db()

    # User accounts
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user'
        )
    """)

    # Expenses table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            expense_date TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # Check old expenses table columns
    expense_columns = [
        row["name"]
        for row in conn.execute(
            "PRAGMA table_info(expenses)"
        ).fetchall()
    ]

    # Add missing columns to old expenses table
    if "user_id" not in expense_columns:
        conn.execute(
            "ALTER TABLE expenses ADD COLUMN user_id INTEGER"
        )

    if "expense_date" not in expense_columns:
        conn.execute(
            "ALTER TABLE expenses ADD COLUMN expense_date TEXT"
        )

    # Give old expenses a date if missing
    conn.execute("""
        UPDATE expenses
        SET expense_date = ?
        WHERE expense_date IS NULL OR expense_date = ''
    """, (date.today().isoformat(),))

    # Create budgets table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            month TEXT NOT NULL,
            amount REAL NOT NULL,
            UNIQUE(user_id, month),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # Check old budgets table columns
    budget_columns = [
        row["name"]
        for row in conn.execute(
            "PRAGMA table_info(budgets)"
        ).fetchall()
    ]

    # Add missing user_id column to old budgets table
    if "user_id" not in budget_columns:
        conn.execute(
            "ALTER TABLE budgets ADD COLUMN user_id INTEGER"
        )

    # Ensure one budget per user per month
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_budgets_user_month
        ON budgets(user_id, month)
    """)

    # Create owner account only if one does not exist
    owner = conn.execute(
        "SELECT id FROM users WHERE role = 'owner'"
    ).fetchone()

    if not owner:
        owner_username = os.environ.get(
            "OWNER_USERNAME", "owner"
        )
        owner_password = os.environ.get("OWNER_PASSWORD")

        if not owner_password:
            owner_password = "ChangeMe123!"

        conn.execute("""
            INSERT INTO users (username, password, role)
            VALUES (?, ?, 'owner')
        """, (
            owner_username,
            generate_password_hash(owner_password)
        ))

    conn.commit()
    conn.close()


# Public registration
@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("home"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or len(password) < 8:
            flash(
                "Enter a username and a password of at least 8 characters."
            )
            return redirect(url_for("register"))

        conn = get_db()

        try:
            conn.execute("""
                INSERT INTO users (username, password, role)
                VALUES (?, ?, 'user')
            """, (
                username,
                generate_password_hash(password)
            ))
            conn.commit()
            flash("Account created! Please log in.")
            return redirect(url_for("login"))

        except sqlite3.IntegrityError:
            flash("That username is already taken.")

        finally:
            conn.close()

    return render_template("register.html")


# Login for owner and public users
@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        if current_user.role == "owner":
            return redirect(url_for("owner_dashboard"))
        return redirect(url_for("home"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,)
        ).fetchone()
        conn.close()

        if user and check_password_hash(user["password"], password):
            login_user(
                  User(
                      user["id"],
                      user["username"],
                      user["role"],
                      user["password"]
            )
        )

            print("Logged in username:", user["username"])
            print("Logged in role:", user["role"])

            if user["role"] == "owner":
                return redirect(url_for("owner_dashboard"))

            return redirect(url_for("home"))

        flash("Invalid username or password.")

    return render_template("login.html")


# Logout
@app.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have logged out successfully.")
    return redirect(url_for("login"))


# Owner dashboard
@app.route("/owner")
@owner_required
def owner_dashboard():
    conn = get_db()

    total_users = conn.execute(
        "SELECT COUNT(*) FROM users WHERE role = 'user'"
    ).fetchone()[0]

    total_expenses = conn.execute(
        "SELECT COUNT(*) FROM expenses"
    ).fetchone()[0]

    users = conn.execute("""
        SELECT id, username
        FROM users
        WHERE role = 'user'
        ORDER BY id DESC
    """).fetchall()

    user_expenses = conn.execute("""
        SELECT expenses.id,
               users.username,
               expenses.name,
               expenses.amount,
               expenses.category,
               expenses.expense_date
        FROM expenses
        JOIN users ON expenses.user_id = users.id
        WHERE users.role = 'user'
        ORDER BY expenses.id DESC
    """).fetchall()

    conn.close()

    return render_template(
        "owner.html",
        total_users=total_users,
        total_expenses=total_expenses,
        users=users,
        user_expenses=user_expenses
    )


# User expense dashboard
@app.route("/", methods=["GET", "POST"])
@login_required
def home():
    if current_user.role == "owner":
        return redirect(url_for("owner_dashboard"))

    conn = get_db()

    if request.method == "POST":
        name = request.form.get("expense_name", "").strip()

        try:
            amount = float(request.form.get("amount", 0))
        except ValueError:
            amount = 0

        category = request.form.get("category", "")
        expense_date = (
            request.form.get("expense_date")
            or date.today().isoformat()
        )

        if name and amount > 0 and category:
            conn.execute("""
                INSERT INTO expenses
                (user_id, name, amount, category, expense_date)
                VALUES (?, ?, ?, ?, ?)
            """, (
                current_user.id,
                name,
                amount,
                category,
                expense_date
            ))
            conn.commit()

        conn.close()
        return redirect(
            url_for("home", month=expense_date[:7])
        )

    selected_month = request.args.get("month", "all")

    months = conn.execute("""
        SELECT DISTINCT substr(expense_date, 1, 7) AS month
        FROM expenses
        WHERE user_id = ?
        ORDER BY month DESC
    """, (current_user.id,)).fetchall()

    monthly_totals = conn.execute("""
        SELECT substr(expense_date, 1, 7) AS month,
               SUM(amount) AS total
        FROM expenses
        WHERE user_id = ?
        GROUP BY substr(expense_date, 1, 7)
        ORDER BY month DESC
    """, (current_user.id,)).fetchall()

    if selected_month == "all":
        expenses = conn.execute("""
            SELECT * FROM expenses
            WHERE user_id = ?
            ORDER BY id DESC
        """, (current_user.id,)).fetchall()
    else:
        expenses = conn.execute("""
            SELECT * FROM expenses
            WHERE user_id = ?
            AND substr(expense_date, 1, 7) = ?
            ORDER BY id DESC
        """, (
            current_user.id,
            selected_month
        )).fetchall()

    total_expenses = sum(
        item["amount"] for item in expenses
    )

    if selected_month == "all":
        category_totals = conn.execute("""
            SELECT category, SUM(amount) AS total
            FROM expenses
            WHERE user_id = ?
            GROUP BY category
            ORDER BY total DESC
        """, (current_user.id,)).fetchall()
    else:
        category_totals = conn.execute("""
            SELECT category, SUM(amount) AS total
            FROM expenses
            WHERE user_id = ?
            AND substr(expense_date, 1, 7) = ?
            GROUP BY category
            ORDER BY total DESC
        """, (
            current_user.id,
            selected_month
        )).fetchall()

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

    monthly_budget = 0

    if selected_month != "all":
        budget_row = conn.execute("""
            SELECT amount FROM budgets
            WHERE user_id = ? AND month = ?
        """, (
            current_user.id,
            selected_month
        )).fetchone()

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


# Set monthly budget
@app.route("/set-budget", methods=["POST"])
@login_required
def set_budget():
    if current_user.role != "user":
        return redirect(url_for("owner_dashboard"))

    month = request.form.get("month")

    try:
        amount = float(request.form.get("budget", 0))
    except ValueError:
        amount = 0

    if month and amount > 0:
        conn = get_db()

        conn.execute("""
            INSERT INTO budgets (user_id, month, amount)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, month)
            DO UPDATE SET amount = excluded.amount
        """, (
            current_user.id,
            month,
            amount
        ))

        conn.commit()
        conn.close()

    return redirect(url_for("home", month=month))


# Delete an expense belonging to the logged-in user
@app.route("/delete/<int:index>", methods=["POST"])
@login_required
def delete_expense(index):
    if current_user.role != "user":
        return redirect(url_for("owner_dashboard"))

    month = request.form.get("month", "all")

    conn = get_db()

    conn.execute("""
        DELETE FROM expenses
        WHERE id = ? AND user_id = ?
    """, (
        index,
        current_user.id
    ))

    conn.commit()
    conn.close()

    return redirect(url_for("home", month=month))


# Initialize database
create_table()


if __name__ == "__main__":
    app.run(debug=True)
