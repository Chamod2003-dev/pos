"""
Simple POS System — Backend API
--------------------------------
Flask + SQLite REST API that powers the POS frontend.

Run:
    pip install -r requirements.txt
    python app.py

Server starts on http://localhost:5000
The database file (pos.db) is created automatically on first run,
with a handful of demo categories/products seeded in.
"""

import os
import sqlite3
from datetime import datetime, date
from flask import Flask, g, jsonify, request
from flask_cors import CORS

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "pos.db")

app = Flask(__name__)
CORS(app)  # allow the frontend (served separately) to call this API


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    fresh = not os.path.exists(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            color TEXT DEFAULT '#4F46E5'
        );

        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price REAL NOT NULL,
            cost REAL DEFAULT 0,
            sku TEXT UNIQUE,
            barcode TEXT UNIQUE,
            category_id INTEGER,
            stock REAL DEFAULT 0,
            track_stock INTEGER DEFAULT 0,
            image_emoji TEXT DEFAULT '🛒',
            active INTEGER DEFAULT 1,
            FOREIGN KEY (category_id) REFERENCES categories(id)
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_number TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            customer_name TEXT DEFAULT 'Walk-in Customer',
            subtotal REAL NOT NULL,
            discount REAL DEFAULT 0,
            tax REAL DEFAULT 0,
            total REAL NOT NULL,
            payment_method TEXT NOT NULL,
            amount_tendered REAL,
            change_due REAL,
            session_id INTEGER,
            status TEXT DEFAULT 'completed'
        );

        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product_id INTEGER,
            product_name TEXT NOT NULL,
            unit_price REAL NOT NULL,
            quantity REAL NOT NULL,
            line_total REAL NOT NULL,
            FOREIGN KEY (order_id) REFERENCES orders(id),
            FOREIGN KEY (product_id) REFERENCES products(id)
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cashier_name TEXT NOT NULL,
            opening_cash REAL DEFAULT 0,
            closing_cash REAL,
            opened_at TEXT NOT NULL,
            closed_at TEXT,
            status TEXT DEFAULT 'open'
        );
        """
    )
    conn.commit()

    # -------------------------------------------------------------------
    # Database migrations
    # -------------------------------------------------------------------

    try:
        conn.execute("ALTER TABLE products ADD COLUMN barcode TEXT")
    
        conn.commit()
    except sqlite3.OperationalError:
        pass

    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_products_barcode
        ON products(barcode)
        WHERE barcode IS NOT NULL AND barcode != ''
    """)
    conn.commit()

def seed_demo_data(conn):
    categories = [
        ("Beverages", "#0EA5E9"),
        ("Bakery", "#F59E0B"),
        ("Snacks", "#10B981"),
        ("Grocery", "#8B5CF6"),
    ]
    conn.executemany("INSERT INTO categories (name, color) VALUES (?, ?)", categories)

    cat_ids = {row[0]: row[1] for row in conn.execute("SELECT name, id FROM categories")}

    products = [
        ("Espresso", 2.50, 0.60, "BEV-001", cat_ids["Beverages"], 100, 0, "☕"),
        ("Cappuccino", 3.20, 0.80, "BEV-002", cat_ids["Beverages"], 100, 0, "☕"),
        ("Orange Juice", 3.00, 1.00, "BEV-003", cat_ids["Beverages"], 50, 1, "🧃"),
        ("Bottled Water", 1.50, 0.40, "BEV-004", cat_ids["Beverages"], 200, 1, "💧"),
        ("Croissant", 2.80, 0.90, "BAK-001", cat_ids["Bakery"], 40, 1, "🥐"),
        ("Chocolate Muffin", 3.10, 1.00, "BAK-002", cat_ids["Bakery"], 35, 1, "🧁"),
        ("Baguette", 2.20, 0.70, "BAK-003", cat_ids["Bakery"], 30, 1, "🥖"),
        ("Potato Chips", 1.80, 0.60, "SNK-001", cat_ids["Snacks"], 80, 1, "🍟"),
        ("Chocolate Bar", 2.00, 0.70, "SNK-002", cat_ids["Snacks"], 90, 1, "🍫"),
        ("Mixed Nuts", 4.50, 2.00, "SNK-003", cat_ids["Snacks"], 45, 1, "🥜"),
        ("Milk 1L", 2.30, 1.10, "GRO-001", cat_ids["Grocery"], 60, 1, "🥛"),
        ("Eggs (12pk)", 3.80, 2.00, "GRO-002", cat_ids["Grocery"], 40, 1, "🥚"),
        ("Rice 1kg", 3.50, 1.80, "GRO-003", cat_ids["Grocery"], 70, 1, "🍚"),
        ("Pasta 500g", 1.90, 0.80, "GRO-004", cat_ids["Grocery"], 65, 1, "🍝"),
    ]
    conn.executemany(
        """INSERT INTO products
           (name, price, cost, sku, category_id, stock, track_stock, image_emoji)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        products,
    )
    conn.commit()


def row_to_dict(row):
    return {k: row[k] for k in row.keys()}


def next_order_number(conn):
    today_str = date.today().strftime("%Y%m%d")
    cur = conn.execute(
        "SELECT COUNT(*) as c FROM orders WHERE order_number LIKE ?", (f"{today_str}-%",)
    )
    count = cur.fetchone()["c"] + 1
    return f"{today_str}-{count:04d}"


# ---------------------------------------------------------------------------
# Category endpoints
# ---------------------------------------------------------------------------

@app.route("/api/categories", methods=["GET"])
def get_categories():
    db = get_db()
    rows = db.execute("SELECT * FROM categories ORDER BY name").fetchall()
    return jsonify([row_to_dict(r) for r in rows])


@app.route("/api/categories", methods=["POST"])
def create_category():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    color = data.get("color") or "#4F46E5"
    if not name:
        return jsonify({"error": "Category name is required"}), 400
    db = get_db()
    try:
        cur = db.execute("INSERT INTO categories (name, color) VALUES (?, ?)", (name, color))
        db.commit()
    except sqlite3.IntegrityError:
        return jsonify({"error": "Category already exists"}), 409
    return jsonify({"id": cur.lastrowid, "name": name, "color": color}), 201


@app.route("/api/categories/<int:cat_id>", methods=["DELETE"])
def delete_category(cat_id):
    db = get_db()
    db.execute("DELETE FROM categories WHERE id = ?", (cat_id,))
    db.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Product endpoints
# ---------------------------------------------------------------------------

@app.route("/api/products", methods=["GET"])
def get_products():
    db = get_db()
    category_id = request.args.get("category_id")
    search = request.args.get("search")

    query = """
        SELECT p.*, c.name as category_name, c.color as category_color
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        WHERE p.active = 1
    """
    params = []
    if category_id:
        query += " AND p.category_id = ?"
        params.append(category_id)
    if search:
        query += " AND (p.name LIKE ? OR p.sku LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
    query += " ORDER BY p.name"

    rows = db.execute(query, params).fetchall()
    return jsonify([row_to_dict(r) for r in rows])


@app.route("/api/products/<int:product_id>", methods=["GET"])
def get_product(product_id):
    db = get_db()
    row = db.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    if not row:
        return jsonify({"error": "Product not found"}), 404
    return jsonify(row_to_dict(row))


@app.route("/api/products", methods=["POST"])
def create_product():
    data = request.get_json(force=True)
    required = ["name", "price"]
    for field in required:
        if data.get(field) in (None, ""):
            return jsonify({"error": f"'{field}' is required"}), 400

    db = get_db()
    cur = db.execute(
        """INSERT INTO products
           (name, price, cost, sku, category_id, stock, track_stock, image_emoji, active)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)""",
        (
            data["name"],
            float(data["price"]),
            float(data.get("cost", 0)),
            data.get("sku"),
            data.get("category_id"),
            float(data.get("stock", 0)),
            1 if data.get("track_stock") else 0,
            data.get("image_emoji", "🛒"),
        ),
    )
    db.commit()
    return jsonify({"id": cur.lastrowid}), 201


@app.route("/api/products/<int:product_id>", methods=["PUT"])
def update_product(product_id):
    data = request.get_json(force=True)
    db = get_db()
    existing = db.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    if not existing:
        return jsonify({"error": "Product not found"}), 404

    fields = ["name", "price", "cost", "sku", "category_id", "stock", "track_stock", "image_emoji", "active"]
    updates = {f: data[f] for f in fields if f in data}
    if not updates:
        return jsonify({"error": "No fields to update"}), 400

    set_clause = ", ".join(f"{f} = ?" for f in updates)
    db.execute(f"UPDATE products SET {set_clause} WHERE id = ?", (*updates.values(), product_id))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/products/<int:product_id>", methods=["DELETE"])
def delete_product(product_id):
    db = get_db()
    # Soft delete so historical orders still reference a valid product row
    db.execute("UPDATE products SET active = 0 WHERE id = ?", (product_id,))
    db.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Order endpoints
# ---------------------------------------------------------------------------

@app.route("/api/orders", methods=["POST"])
def create_order():
    data = request.get_json(force=True)
    items = data.get("items") or []
    if not items:
        return jsonify({"error": "Order must contain at least one item"}), 400

    payment_method = data.get("payment_method", "cash")
    discount = float(data.get("discount", 0))
    tax_rate = float(data.get("tax_rate", 0))
    customer_name = data.get("customer_name") or "Walk-in Customer"
    amount_tendered = data.get("amount_tendered")

    subtotal = sum(float(i["price"]) * float(i["quantity"]) for i in items)
    discounted = max(subtotal - discount, 0)
    tax = round(discounted * tax_rate / 100, 2)
    total = round(discounted + tax, 2)

    change_due = None
    if payment_method == "cash" and amount_tendered is not None:
        change_due = round(float(amount_tendered) - total, 2)

    db = get_db()
    # ---------------------------------------------------------------
    # Current counter session
    # ---------------------------------------------------------------

    session = db.execute(
        """
        SELECT *
        FROM sessions
        WHERE status = 'open'
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()

    if not session:
        return jsonify({
            "error": "No counter session is open. Please open the counter first."
        }), 400

    session_id = session["id"]

    order_number = next_order_number(db)
    cur = db.execute(
    """INSERT INTO orders
       (
           order_number,
           created_at,
           customer_name,
           subtotal,
           discount,
           tax,
           total,
           payment_method,
           amount_tendered,
           change_due,
           session_id,
           status
       )
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'completed')""",
       (
            order_number,
            datetime.now().isoformat(timespec="seconds"),
            customer_name,
            round(subtotal, 2),
            round(discount, 2),
            tax,
            total,
            payment_method,
            amount_tendered,
            change_due,
            session_id,
        ),
    )
    order_id = cur.lastrowid

    for item in items:
        line_total = round(float(item["price"]) * float(item["quantity"]), 2)
        db.execute(
            """INSERT INTO order_items
               (order_id, product_id, product_name, unit_price, quantity, line_total)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (order_id, item.get("product_id"), item["name"], item["price"], item["quantity"], line_total),
        )
        # decrement stock for tracked products
        if item.get("product_id"):
            db.execute(
                """UPDATE products SET stock = stock - ?
                   WHERE id = ? AND track_stock = 1""",
                (item["quantity"], item["product_id"]),
            )

    db.commit()

    order_row = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    item_rows = db.execute("SELECT * FROM order_items WHERE order_id = ?", (order_id,)).fetchall()

    result = row_to_dict(order_row)
    result["items"] = [row_to_dict(r) for r in item_rows]
    return jsonify(result), 201


@app.route("/api/orders", methods=["GET"])
def get_orders():
    db = get_db()
    day = request.args.get("date")  # format YYYY-MM-DD
    query = "SELECT * FROM orders"
    params = []
    if day:
        query += " WHERE created_at LIKE ?"
        params.append(f"{day}%")
    query += " ORDER BY id DESC LIMIT 200"
    rows = db.execute(query, params).fetchall()
    return jsonify([row_to_dict(r) for r in rows])


@app.route("/api/orders/<int:order_id>", methods=["GET"])
def get_order(order_id):
    db = get_db()
    order_row = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if not order_row:
        return jsonify({"error": "Order not found"}), 404
    item_rows = db.execute("SELECT * FROM order_items WHERE order_id = ?", (order_id,)).fetchall()
    result = row_to_dict(order_row)
    result["items"] = [row_to_dict(r) for r in item_rows]
    return jsonify(result)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

@app.route("/api/reports/summary", methods=["GET"])
def report_summary():
    db = get_db()
    day = request.args.get("date", date.today().isoformat())

    row = db.execute(
        """SELECT COUNT(*) as order_count,
                  COALESCE(SUM(total), 0) as total_sales,
                  COALESCE(SUM(tax), 0) as total_tax,
                  COALESCE(SUM(discount), 0) as total_discount
           FROM orders WHERE created_at LIKE ? AND status = 'completed'""",
        (f"{day}%",),
    ).fetchone()

    top_items = db.execute(
        """SELECT oi.product_name, SUM(oi.quantity) as qty, SUM(oi.line_total) as revenue
           FROM order_items oi
           JOIN orders o ON oi.order_id = o.id
           WHERE o.created_at LIKE ? AND o.status = 'completed'
           GROUP BY oi.product_name
           ORDER BY revenue DESC
           LIMIT 5""",
        (f"{day}%",),
    ).fetchall()

    payment_breakdown = db.execute(
        """SELECT payment_method, COUNT(*) as count, COALESCE(SUM(total), 0) as total
           FROM orders WHERE created_at LIKE ? AND status = 'completed'
           GROUP BY payment_method""",
        (f"{day}%",),
    ).fetchall()

    return jsonify(
        {
            "date": day,
            "order_count": row["order_count"],
            "total_sales": round(row["total_sales"], 2),
            "total_tax": round(row["total_tax"], 2),
            "total_discount": round(row["total_discount"], 2),
            "top_items": [row_to_dict(r) for r in top_items],
            "payment_breakdown": [row_to_dict(r) for r in payment_breakdown],
        }
    )


# ---------------------------------------------------------------------------
# Register sessions ("counter") — open/close, 24h auto-expiry
# ---------------------------------------------------------------------------

SESSION_MAX_HOURS = 24


@app.route("/api/sessions/current", methods=["GET"])
def get_current_session():

    db = get_db()

    row = db.execute(
        """
        SELECT *
        FROM sessions
        WHERE status = 'open'
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()

    if not row:
        return jsonify(None)

    session = row_to_dict(row)

    # ---------------------------------------------------------------
    # Session time
    # ---------------------------------------------------------------

    opened_at = datetime.fromisoformat(
        session["opened_at"]
    )

    elapsed_hours = (
        datetime.now() - opened_at
    ).total_seconds() / 3600

    session["expired"] = (
        elapsed_hours >= SESSION_MAX_HOURS
    )

    session["max_hours"] = SESSION_MAX_HOURS

    # ---------------------------------------------------------------
    # Cash sales for this session
    # ---------------------------------------------------------------

    cash_row = db.execute(
        """
        SELECT
            COALESCE(SUM(total), 0) AS cash_sales
        FROM orders
        WHERE session_id = ?
          AND payment_method = 'cash'
          AND status = 'completed'
        """,
        (session["id"],)
    ).fetchone()

    cash_sales = float(
        cash_row["cash_sales"] or 0
    )

    session["cash_sales"] = round(
        cash_sales,
        2
    )

    # ---------------------------------------------------------------
    # All sales
    # ---------------------------------------------------------------

    sales_row = db.execute(
        """
        SELECT
            COUNT(*) AS order_count,
            COALESCE(SUM(total), 0) AS total_sales
        FROM orders
        WHERE session_id = ?
          AND status = 'completed'
        """,
        (session["id"],)
    ).fetchone()

    session["order_count"] = (
        sales_row["order_count"] or 0
    )

    session["total_sales"] = round(
        float(sales_row["total_sales"] or 0),
        2
    )

    # ---------------------------------------------------------------
    # Expected cash
    #
    # Opening Cash + Cash Sales
    # ---------------------------------------------------------------

    opening_cash = float(
        session["opening_cash"] or 0
    )

    session["expected_cash"] = round(
        opening_cash + cash_sales,
        2
    )

    return jsonify(session)


@app.route("/api/sessions", methods=["POST"])
def open_session():

    data = request.get_json(force=True)

    cashier_name = (
        data.get("cashier_name") or ""
    ).strip()

    if not cashier_name:
        return jsonify({
            "error": "Cashier name is required"
        }), 400

    try:
        opening_cash = float(
            data.get("opening_cash", 0)
        )
    except (TypeError, ValueError):
        return jsonify({
            "error": "Invalid opening cash"
        }), 400

    if opening_cash < 0:
        return jsonify({
            "error": "Opening cash cannot be negative"
        }), 400

    db = get_db()

    # ---------------------------------------------------------------
    # Don't allow two open counters
    # ---------------------------------------------------------------

    existing = db.execute(
        """
        SELECT id
        FROM sessions
        WHERE status = 'open'
        LIMIT 1
        """
    ).fetchone()

    if existing:
        return jsonify({
            "error": "A counter session is already open"
        }), 400

    # ---------------------------------------------------------------
    # Open new session
    # ---------------------------------------------------------------

    opened_at = datetime.now().isoformat(
        timespec="seconds"
    )

    cur = db.execute(
        """
        INSERT INTO sessions
        (
            cashier_name,
            opening_cash,
            opened_at,
            status
        )
        VALUES (?, ?, ?, 'open')
        """,
        (
            cashier_name,
            opening_cash,
            opened_at
        )
    )

    db.commit()

    row = db.execute(
        """
        SELECT *
        FROM sessions
        WHERE id = ?
        """,
        (cur.lastrowid,)
    ).fetchone()

    session = row_to_dict(row)

    session["expired"] = False
    session["max_hours"] = SESSION_MAX_HOURS
    session["cash_sales"] = 0
    session["total_sales"] = 0
    session["order_count"] = 0
    session["expected_cash"] = opening_cash

    return jsonify(session), 201


@app.route("/api/sessions/<int:session_id>/close", methods=["POST"])
def close_session(session_id):

    data = request.get_json(silent=True) or {}

    if "closing_cash" not in data:
        return jsonify({
            "error": "Closing cash is required"
        }), 400

    try:
        closing_cash = float(
            data["closing_cash"]
        )
    except (TypeError, ValueError):
        return jsonify({
            "error": "Invalid closing cash"
        }), 400

    if closing_cash < 0:
        return jsonify({
            "error": "Closing cash cannot be negative"
        }), 400

    db = get_db()

    # ---------------------------------------------------------------
    # Find open session
    # ---------------------------------------------------------------

    session = db.execute(
        """
        SELECT *
        FROM sessions
        WHERE id = ?
          AND status = 'open'
        """,
        (session_id,)
    ).fetchone()

    if not session:
        return jsonify({
            "error": "Open counter session not found"
        }), 404

    # ---------------------------------------------------------------
    # Calculate cash sales
    # ---------------------------------------------------------------

    cash_row = db.execute(
        """
        SELECT
            COALESCE(SUM(total), 0) AS cash_sales
        FROM orders
        WHERE session_id = ?
          AND payment_method = 'cash'
          AND status = 'completed'
        """,
        (session_id,)
    ).fetchone()

    cash_sales = float(
        cash_row["cash_sales"] or 0
    )

    # ---------------------------------------------------------------
    # Expected cash
    # ---------------------------------------------------------------

    opening_cash = float(
        session["opening_cash"] or 0
    )

    expected_cash = round(
        opening_cash + cash_sales,
        2
    )

    # ---------------------------------------------------------------
    # Difference
    # ---------------------------------------------------------------

    difference = round(
        closing_cash - expected_cash,
        2
    )

    # ---------------------------------------------------------------
    # Close session
    # ---------------------------------------------------------------

    closed_at = datetime.now().isoformat(
        timespec="seconds"
    )

    db.execute(
        """
        UPDATE sessions
        SET
            closing_cash = ?,
            closed_at = ?,
            status = 'closed'
        WHERE id = ?
        """,
        (
            closing_cash,
            closed_at,
            session_id
        )
    )

    db.commit()

    return jsonify({
        "ok": True,
        "session_id": session_id,
        "cashier_name": session["cashier_name"],
        "opening_cash": opening_cash,
        "cash_sales": cash_sales,
        "expected_cash": expected_cash,
        "closing_cash": closing_cash,
        "difference": difference,
        "closed_at": closed_at
    })


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "time": datetime.now().isoformat()})


if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)