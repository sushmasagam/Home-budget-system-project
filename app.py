
from flask import Flask, render_template, request, redirect, url_for, jsonify
import mysql.connector
from datetime import date, datetime
from decimal import Decimal

app = Flask(__name__)

# Database connection
def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="password",
        database="home_budget_db"
    )


# Generate budget alerts automatically
def generate_budget_alerts():
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            b.user_id,
            b.category_id,
            b.budget_amount,
            b.month,
            c.category_name,
            COALESCE(SUM(e.amount), 0) AS spent
        FROM budgets b
        JOIN categories c ON b.category_id = c.category_id
        LEFT JOIN expenses e
            ON e.category_id = b.category_id
            AND e.user_id = b.user_id
            AND DATE_FORMAT(e.expense_date, '%Y-%m') =
                DATE_FORMAT(b.month, '%Y-%m')
        GROUP BY b.budget_id, b.user_id, b.category_id,
                 b.budget_amount, b.month, c.category_name
    """)

    budgets = cursor.fetchall()

    for item in budgets:
        budget = Decimal(str(item["budget_amount"]))
        spent = Decimal(str(item["spent"]))

        if spent >= budget:
            message = (
                f'{item["category_name"]} budget exceeded! '
                f'Budget: Rs. {budget}, Expenses: Rs. {spent}, '
                f'Overspending: Rs. {spent - budget}.'
            )
        elif spent >= budget * Decimal("0.80"):
            message = (
                f'{item["category_name"]} budget warning! '
                f'Budget: Rs. {budget}, Expenses: Rs. {spent}.'
            )
        else:
            continue

        cursor.execute("""
            SELECT alert_id FROM alerts
            WHERE user_id = %s AND message = %s
        """, (item["user_id"], message))

        if not cursor.fetchone():
            cursor.execute("""
                INSERT INTO alerts (user_id, alert_date, message)
                VALUES (%s, %s, %s)
            """, (item["user_id"], date.today(), message))

    db.commit()
    cursor.close()
    db.close()


# Home dashboard
@app.route("/")
def dashboard():
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT COALESCE(SUM(amount), 0) AS total FROM expenses")
    total_expenses = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) AS total FROM expenses")
    expense_count = cursor.fetchone()["total"]

    cursor.execute("""
        SELECT c.category_name, SUM(e.amount) AS total
        FROM expenses e
        JOIN categories c ON e.category_id = c.category_id
        GROUP BY c.category_name
    """)
    category_totals = cursor.fetchall()

    cursor.execute("SELECT * FROM alerts ORDER BY alert_date DESC LIMIT 5")
    recent_alerts = cursor.fetchall()

    cursor.close()
    db.close()

    return render_template(
        "dashboard.html",
        total_expenses=total_expenses,
        expense_count=expense_count,
        category_totals=category_totals,
        alerts=recent_alerts
    )


# Add and display expenses
@app.route("/expenses", methods=["GET", "POST"])
def expenses():
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    if request.method == "POST":
        amount = request.form["amount"]
        category_id = request.form["category_id"]
        description = request.form["description"]
        expense_date = request.form["expense_date"]

        cursor.execute("""
            INSERT INTO expenses
            (user_id, category_id, amount, description, expense_date)
            VALUES (1, %s, %s, %s, %s)
        """, (category_id, amount, description, expense_date))

        cursor.execute("""
            INSERT INTO audit_logs (user_id, action, log_date)
            VALUES (1, %s, NOW())
        """, ("Added an expense",))

        db.commit()
        cursor.close()
        db.close()

        generate_budget_alerts()
        return redirect(url_for("expenses"))

    cursor.execute("SELECT * FROM categories")
    categories = cursor.fetchall()

    cursor.execute("""
        SELECT e.*, c.category_name
        FROM expenses e
        JOIN categories c ON e.category_id = c.category_id
        ORDER BY e.expense_date DESC
    """)
    expense_list = cursor.fetchall()

    cursor.close()
    db.close()

    return render_template(
        "expenses.html",
        categories=categories,
        expenses=expense_list,
        today=date.today().isoformat()
    )


# Alerts page
@app.route("/alerts")
def alerts():
    generate_budget_alerts()

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT * FROM alerts ORDER BY alert_date DESC")
    alert_list = cursor.fetchall()

    cursor.close()
    db.close()

    return render_template("alerts.html", alerts=alert_list)


# Review an alert
@app.route("/alerts/review/<int:alert_id>", methods=["POST"])
def review_alert(alert_id):
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT * FROM alerts WHERE alert_id = %s", (alert_id,))
    alert = cursor.fetchone()

    if alert:
        cursor.execute("""
            INSERT INTO audit_logs (user_id, action, log_date)
            VALUES (%s, %s, NOW())
        """, (alert["user_id"], f'Reviewed alert {alert_id}'))

        db.commit()

    cursor.close()
    db.close()

    return redirect(url_for("alerts"))


# Audit Log page
@app.route("/audit-logs")
def audit_logs():
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT * FROM audit_logs
        ORDER BY log_date DESC
    """)
    logs = cursor.fetchall()

    cursor.close()
    db.close()

    return render_template("audit_log.html", logs=logs)


# Reports page

def reports():
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT category_id, COUNT(*) AS expense_count,
               SUM(amount) AS total_amount,
               AVG(amount) AS average_amount,
               MIN(amount) AS minimum_amount,
               MAX(amount) AS maximum_amount
        FROM expenses
        GROUP BY category_id
    """)
    statistics = cursor.fetchall()

    cursor.execute("""
        SELECT DATE_FORMAT(expense_date, '%Y-%m') AS month,
               SUM(amount) AS total
        FROM expenses
        GROUP BY DATE_FORMAT(expense_date, '%Y-%m')
        ORDER BY month
    """)
    monthly_trend = cursor.fetchall()

    cursor.close()
    db.close()

    return render_template(
        "reports.html",
        statistics=statistics,
        monthly_trend=monthly_trend
    )


# Category analysis page
@app.route("/category-analysis")
def category_analysis():
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT c.category_name,
               COALESCE(SUM(e.amount), 0) AS total,
               COUNT(e.expense_id) AS expense_count
        FROM categories c
        LEFT JOIN expenses e ON c.category_id = e.category_id
        GROUP BY c.category_id, c.category_name
        ORDER BY total DESC
    """)
    categories = cursor.fetchall()

    cursor.close()
    db.close()

    return render_template(
    "category_analysis.html",
    category_data=categories
)


# Expense risk analysis
@app.route("/api/expenses/<int:expense_id>/risk")
def expense_risk(expense_id):
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT e.*, c.category_name
        FROM expenses e
        JOIN categories c ON e.category_id = c.category_id
        WHERE e.expense_id = %s
    """, (expense_id,))

    expense = cursor.fetchone()

    if not expense:
        cursor.close()
        db.close()
        return jsonify({"error": "Expense not found"}), 404

    cursor.execute("""
        SELECT budget_amount FROM budgets
        WHERE user_id = %s
          AND category_id = %s
          AND DATE_FORMAT(month, '%Y-%m') =
              DATE_FORMAT(%s, '%Y-%m')
    """, (
        expense["user_id"],
        expense["category_id"],
        expense["expense_date"]
    ))

    budget = cursor.fetchone()
    score = 20
    risk_level = "Low"

    if budget:
        amount = Decimal(str(expense["amount"]))
        limit = Decimal(str(budget["budget_amount"]))

        if amount >= limit:
            score = 90
            risk_level = "High"
        elif amount >= limit * Decimal("0.8"):
            score = 60
            risk_level = "Medium"

    cursor.close()
    db.close()

    return jsonify({
        "expense_id": expense_id,
        "category": expense["category_name"],
        "amount": float(expense["amount"]),
        "risk_score": score,
        "risk_level": risk_level
    })


# Health API
@app.route("/api/health")
def health():
    return jsonify({
        "status": "healthy",
        "project": "Home Budget System"
    })


# Users API
@app.route("/api/users")
def users_api():
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT user_id, username, email FROM users")
    data = cursor.fetchall()

    cursor.close()
    db.close()
    return jsonify(data)


# Categories API
@app.route("/api/categories")
def categories_api():
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT * FROM categories")
    data = cursor.fetchall()

    cursor.close()
    db.close()
    return jsonify(data)


# Expenses API
@app.route("/api/expenses")
def expenses_api():
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT e.*, c.category_name
        FROM expenses e
        JOIN categories c ON e.category_id = c.category_id
    """)
    data = cursor.fetchall()

    cursor.close()
    db.close()
    return jsonify(data)


# Alerts API
@app.route("/api/alerts")
def alerts_api():
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT * FROM alerts")
    data = cursor.fetchall()

    cursor.close()
    db.close()
    return jsonify(data)


@app.route("/audit-log")
def audit_log():
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT log_id, user_id, action, log_date
        FROM audit_logs
        ORDER BY log_date DESC
    """)

    logs = cursor.fetchall()

    cursor.close()
    db.close()

    return render_template("audit_log.html", logs=logs)
@app.route("/reports")
def reports():
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            COALESCE(SUM(amount), 0) AS total_expenses,
            COUNT(*) AS expense_count,
            COALESCE(AVG(amount), 0) AS average_expense
        FROM expenses
    """)
    summary = cursor.fetchone()

    cursor.execute("""
        SELECT
            DATE_FORMAT(expense_date, '%Y-%m') AS month,
            SUM(amount) AS total
        FROM expenses
        GROUP BY DATE_FORMAT(expense_date, '%Y-%m')
        ORDER BY month
    """)
    monthly_data = cursor.fetchall()

    cursor.close()
    db.close()

    return render_template(
        "reports.html",
        total_expenses=summary["total_expenses"],
        expense_count=summary["expense_count"],
        average_expense=round(float(summary["average_expense"]), 2),
        monthly_data=monthly_data
    )


if __name__ == "__main__":
    app.run(debug=True)
