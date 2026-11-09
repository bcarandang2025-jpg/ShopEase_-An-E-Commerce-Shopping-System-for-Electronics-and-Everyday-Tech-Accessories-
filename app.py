
import os
import sqlite3
from functools import wraps

from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    redirect,
    url_for,
    flash,
    session,
)

from database import (
    initialize_database,
    seed_products,
    get_connection,
    view_orders,
    update_delivery_status,
)

from models.payment import MockPayment


# ==========================================
# APPLICATION CONFIGURATION
# ==========================================

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SHOPEASE_SECRET_KEY",
    "local-development-key-change-before-deployment",
)

# Admin credentials for local development.
# Override these using environment variables before deployment.
ADMIN_USERNAME = os.environ.get(
    "SHOPEASE_ADMIN_USERNAME",
    "admin"
)

ADMIN_PASSWORD = os.environ.get(
    "SHOPEASE_ADMIN_PASSWORD",
    "ChangeMe123!"
)
DELIVERY_STATUSES = {
    "Pending",
    "Processing",
    "Shipped",
    "Delivered",
    "Cancelled",
}


# ==========================================
# DATABASE HELPERS
# ==========================================

def get_columns(connection, table):
    """Return the column names of an existing SQLite table."""
    rows = connection.execute(
        f'PRAGMA table_info("{table}")'
    ).fetchall()

    return {
        row["name"] if isinstance(row, sqlite3.Row) else row[1]
        for row in rows
    }


def find_column(columns, *names):
    """Return the first matching column name."""
    for name in names:
        if name in columns:
            return name
    return None


def quote_identifier(identifier):
    """Safely quote a database identifier selected from known columns."""
    return '"' + identifier.replace('"', '""') + '"'


def row_to_dict(row):
    """Convert a SQLite row or dictionary into a dictionary."""
    if row is None:
        return None

    if isinstance(row, sqlite3.Row):
        return dict(row)

    if isinstance(row, dict):
        return row

    raise TypeError(
        "Expected a dictionary or sqlite3.Row database record."
    )


def get_order_id(order):
    """Support databases using order_id or id."""
    return order.get("order_id") or order.get("id", "")


def get_order_total(order):
    """Support databases using total or total_amount."""
    return order.get("total") or order.get("total_amount", 0)


# ==========================================
# ADMIN AUTHENTICATION
# ==========================================

def admin_required(view_function):
    """Restrict a route to logged-in administrators."""

    @wraps(view_function)
    def wrapper(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login"))

        return view_function(*args, **kwargs)

    return wrapper


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get("is_admin"):
        return redirect(url_for("order_dashboard"))

    if request.method == "POST":
        username = request.form.get(
            "username", ""
        ).strip()

        password = request.form.get(
            "password", ""
        )

        if (
            username == ADMIN_USERNAME
            and password == ADMIN_PASSWORD
        ):
            session.clear()
            session["is_admin"] = True

            flash(
                "Welcome to ShopEase Admin!",
                "success"
            )

            return redirect(url_for("order_dashboard"))

        flash(
            "Invalid username or password.",
            "error"
        )

    return render_template("admin_login.html")


@app.route("/admin/logout", methods=["POST"])
@admin_required
def admin_logout():
    session.clear()

    flash(
        "You have been logged out successfully.",
        "success"
    )

    return redirect(url_for("admin_login"))
# ==========================================
# HOME / PRODUCT CATALOG
# ==========================================

@app.route("/")
def home():
    connection = get_connection()

    try:
        columns = get_columns(connection, "products")

        product_id_column = find_column(
            columns,
            "product_id",
            "id",
        )

        if not product_id_column:
            raise RuntimeError(
                "The products table has no product ID column."
            )

        required = {"name", "price", "stock"}

        if not required.issubset(columns):
            raise RuntimeError(
                "The products table must contain name, price, and stock."
            )

        description_sql = (
            quote_identifier("description")
            if "description" in columns
            else "''"
        )

        product_id_sql = quote_identifier(product_id_column)

        products = connection.execute(
            f"""
            SELECT
                {product_id_sql} AS id,
                {product_id_sql} AS product_id,
                name,
                {description_sql} AS description,
                price,
                stock
            FROM products
            ORDER BY {product_id_sql}
            """
        ).fetchall()

        # Convert SQLite rows into dictionaries for Jinja templates.
        products = [row_to_dict(row) for row in products]

        return render_template(
            "index.html",
            products=products,
        )

    except (sqlite3.Error, RuntimeError, TypeError):
        app.logger.exception("Unable to load product catalog")

        return (
            "Unable to load products. Check the database "
            "and the products table columns.",
            500,
        )

    finally:
        connection.close()


# ==========================================
# SHOPPING CART
# ==========================================

@app.route("/cart")
def cart_page():
    return render_template("cart.html")


# ==========================================
# CUSTOMER ORDER TRACKING
# ==========================================

@app.route("/track-order")
def track_order():
    order_id = request.args.get("order_id", "").strip()
    order = None
    error = None

    if order_id:
        if not order_id.isdigit() or int(order_id) < 1:
            error = "Please enter a valid order number."

        else:
            try:
                orders = [
                    row_to_dict(row)
                    for row in view_orders()
                ]

                order = next(
                    (
                        item for item in orders
                        if str(get_order_id(item)) == order_id
                    ),
                    None,
                )

                if order is None:
                    error = (
                        "Order not found. "
                        "Please check your order number."
                    )

            except (
                sqlite3.Error,
                RuntimeError,
                TypeError,
                ValueError,
            ):
                app.logger.exception("Order tracking failed")

                error = (
                    "Unable to load your order right now. "
                    "Please try again later."
                )

    return render_template(
        "tracking.html",
        order=order,
        order_id=order_id,
        error=error,
    )


# ==========================================
# ADMIN ORDER DASHBOARD
# ==========================================

@app.route("/admin/orders")
@admin_required
def order_dashboard():
    try:
        orders = [
            row_to_dict(row)
            for row in view_orders()
        ]

    except (
        sqlite3.Error,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        app.logger.exception("Could not load order dashboard")

        orders = []

        flash(
            "Unable to load orders. Please check your database.",
            "error",
        )

    stats = {
        "total": len(orders),
        "pending": 0,
        "processing": 0,
        "shipped": 0,
        "delivered": 0,
        "cancelled": 0,
    }

    for order in orders:
        status = str(
            order.get("delivery_status") or "Pending"
        ).strip().lower()

        if status in stats:
            stats[status] += 1

    return render_template(
        "dashboard.html",
        orders=orders,
        stats=stats,
        error=None,
    )


# ==========================================
# UPDATE ORDER DELIVERY STATUS
# ==========================================

@app.route(
    "/admin/orders/<int:order_id>/status",
    methods=["POST"],
)
@admin_required
def update_order_status(order_id):
    new_status = request.form.get(
        "delivery_status",
        "",
    ).strip()

    if new_status not in DELIVERY_STATUSES:
        flash("Invalid delivery status.", "error")
        return redirect(url_for("order_dashboard"))

    try:
        updated = update_delivery_status(
            order_id,
            new_status,
        )

        if updated:
            flash(
                f"Order #{order_id} status updated to {new_status}.",
                "success",
            )

            return redirect(url_for("order_dashboard"))

        flash(
            f"Order #{order_id} was not found.",
            "error",
        )

    except (sqlite3.Error, ValueError, RuntimeError):
        app.logger.exception(
            "Could not update delivery status"
        )

        flash(
            "Unable to update the delivery status.",
            "error",
        )

    return redirect(url_for("order_dashboard"))


# ==========================================
# CHECKOUT API
# ==========================================

@app.route("/api/checkout", methods=["POST"])
def checkout():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            "error": "Invalid checkout request."
        }), 400

    name = str(data.get("name", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    phone = str(data.get("phone", "")).strip()
    items = data.get("items", [])

    if (
        not name
        or len(name) > 150
        or not email
        or len(email) > 254
        or "@" not in email
        or email.startswith("@")
        or email.endswith("@")
        or any(char.isspace() for char in email)
    ):
        return jsonify({
            "error": "Enter a valid name and email address."
        }), 400

    if len(phone) > 30:
        return jsonify({
            "error": "Phone number is too long."
        }), 400

    if not isinstance(items, list) or not items:
        return jsonify({
            "error": "Your cart is empty."
        }), 400

    # Validate item IDs and quantities.
    quantities = {}

    for item in items:
        if not isinstance(item, dict):
            return jsonify({
                "error": "Invalid cart item."
            }), 400

        product_id = item.get(
            "id",
            item.get("product_id"),
        )
        quantity = item.get("quantity")

        if (
            type(product_id) is not int
            or product_id <= 0
            or type(quantity) is not int
            or quantity <= 0
        ):
            return jsonify({
                "error": "Invalid product ID or quantity."
            }), 400

        quantities[product_id] = (
            quantities.get(product_id, 0) + quantity
        )

        if quantities[product_id] > 10000:
            return jsonify({
                "error": "Requested quantity is too large."
            }), 400

    connection = get_connection()

    try:
        with connection:
            # ----------------------------------
            # DETECT DATABASE COLUMNS
            # ----------------------------------

            product_columns = get_columns(
                connection,
                "products",
            )

            customer_columns = get_columns(
                connection,
                "customers",
            )

            order_columns = get_columns(
                connection,
                "orders",
            )

            item_columns = get_columns(
                connection,
                "order_items",
            )

            product_id_column = find_column(
                product_columns,
                "product_id",
                "id",
            )

            customer_id_column = find_column(
                customer_columns,
                "customer_id",
                "id",
            )

            order_customer_column = find_column(
                order_columns,
                "customer_id",
            )

            order_total_column = find_column(
                order_columns,
                "total",
                "total_amount",
            )

            item_order_id_column = find_column(
                item_columns,
                "order_id",
            )

            item_product_id_column = find_column(
                item_columns,
                "product_id",
            )

            item_quantity_column = find_column(
                item_columns,
                "quantity",
            )

            item_price_column = find_column(
                item_columns,
                "unit_price",
                "price",
            )

            item_subtotal_column = find_column(
                item_columns,
                "subtotal",
            )

            required_columns = [
                product_id_column,
                customer_id_column,
                order_customer_column,
                order_total_column,
                item_order_id_column,
                item_product_id_column,
                item_quantity_column,
                item_price_column,
            ]

            if not all(required_columns):
                raise RuntimeError(
                    "A required database column is missing. "
                    "Check the table definitions in database.py."
                )

            if not {"name", "price", "stock"}.issubset(
                product_columns
            ):
                raise RuntimeError(
                    "The products table needs name, price, and stock."
                )

            if not {"name", "email"}.issubset(customer_columns):
                raise RuntimeError(
                    "The customers table needs name and email."
                )

            # ----------------------------------
            # CHECK PRODUCTS, PRICES, AND STOCK
            # ----------------------------------

            total = 0.0
            checked_items = []

            for product_id, quantity in quantities.items():
                product = connection.execute(
                    f"""
                    SELECT name, price, stock
                    FROM products
                    WHERE {quote_identifier(product_id_column)} = ?
                    """,
                    (product_id,),
                ).fetchone()

                if product is None:
                    raise ValueError(
                        f"Product #{product_id} no longer exists."
                    )

                stock = int(product["stock"])

                if stock < 0 or quantity > stock:
                    raise ValueError(
                        f"Not enough stock for {product['name']}. "
                        f"Available stock: {max(stock, 0)}."
                    )

                price = float(product["price"])

                if price <= 0:
                    raise ValueError(
                        f"Invalid price for {product['name']}."
                    )

                subtotal = round(price * quantity, 2)
                total += subtotal

                checked_items.append({
                    "id": product_id,
                    "name": product["name"],
                    "quantity": quantity,
                    "price": price,
                    "subtotal": subtotal,
                })

            total = round(total, 2)

            if total <= 0:
                raise ValueError(
                    "The order total must be greater than zero."
                )

            # ----------------------------------
            # FIND OR CREATE CUSTOMER
            # ----------------------------------

            customer = connection.execute(
                """
                SELECT *
                FROM customers
                WHERE email = ?
                """,
                (email,),
            ).fetchone()

            if customer:
                customer_id = customer[customer_id_column]

                updates = []
                values = []

                if "name" in customer_columns:
                    updates.append('"name" = ?')
                    values.append(name)

                if "phone" in customer_columns:
                    updates.append('"phone" = ?')
                    values.append(phone)

                if updates:
                    values.append(customer_id)

                    connection.execute(
                        f"""
                        UPDATE customers
                        SET {", ".join(updates)}
                        WHERE {quote_identifier(customer_id_column)} = ?
                        """,
                        values,
                    )

            else:
                insert_columns = ["name", "email"]
                insert_values = [name, email]

                if "phone" in customer_columns:
                    insert_columns.append("phone")
                    insert_values.append(phone)

                placeholders = ", ".join(
                    "?" for _ in insert_values
                )

                cursor = connection.execute(
                    f"""
                    INSERT INTO customers
                        ({", ".join(
                            quote_identifier(column)
                            for column in insert_columns
                        )})
                    VALUES ({placeholders})
                    """,
                    insert_values,
                )

                customer_id = cursor.lastrowid

            # ----------------------------------
            # SIMULATED PAYMENT
            # ----------------------------------

            # This mock payment does not charge real money.
            payment = MockPayment()

            if not payment.pay(total):
                raise ValueError(
                    "Mock payment was unsuccessful."
                )

            # ----------------------------------
            # CREATE ORDER
            # ----------------------------------

            order_insert_columns = [
                order_customer_column,
                order_total_column,
            ]

            order_values = [
                customer_id,
                total,
            ]

            if "status" in order_columns:
                order_insert_columns.append("status")
                order_values.append("Completed (Mock)")

            if "delivery_status" in order_columns:
                order_insert_columns.append("delivery_status")
                order_values.append("Processing")

            placeholders = ", ".join(
                "?" for _ in order_values
            )

            cursor = connection.execute(
                f"""
                INSERT INTO orders
                    ({", ".join(
                        quote_identifier(column)
                        for column in order_insert_columns
                    )})
                VALUES ({placeholders})
                """,
                order_values,
            )

            order_id = cursor.lastrowid

            # ----------------------------------
            # SAVE ORDER ITEMS AND UPDATE STOCK
            # ----------------------------------

            for item in checked_items:
                item_insert_columns = [
                    item_order_id_column,
                    item_product_id_column,
                    item_quantity_column,
                    item_price_column,
                ]

                item_values = [
                    order_id,
                    item["id"],
                    item["quantity"],
                    item["price"],
                ]

                if item_subtotal_column:
                    item_insert_columns.append(
                        item_subtotal_column
                    )
                    item_values.append(item["subtotal"])

                placeholders = ", ".join(
                    "?" for _ in item_values
                )

                connection.execute(
                    f"""
                    INSERT INTO order_items
                        ({", ".join(
                            quote_identifier(column)
                            for column in item_insert_columns
                        )})
                    VALUES ({placeholders})
                    """,
                    item_values,
                )

                result = connection.execute(
                    f"""
                    UPDATE products
                    SET stock = stock - ?
                    WHERE {quote_identifier(product_id_column)} = ?
                      AND stock >= ?
                    """,
                    (
                        item["quantity"],
                        item["id"],
                        item["quantity"],
                    ),
                )

                if result.rowcount != 1:
                    raise ValueError(
                        f"Unable to update stock for {item['name']}."
                    )

        # Transaction committed successfully.
        return jsonify({
            "message": "Order placed successfully!",
            "order_id": order_id,
            "total": total,
            "status": "Completed (Mock)",
            "delivery_status": "Processing",
            "tracking_url": url_for(
                "track_order",
                order_id=order_id,
            ),
        }), 201

    except ValueError as error:
        return jsonify({
            "error": str(error)
        }), 400

    except (
        sqlite3.Error,
        RuntimeError,
        TypeError,
        KeyError,
        OverflowError,
    ):
        app.logger.exception("Checkout failed")

        return jsonify({
            "error": (
                "Checkout failed. Check the database structure "
                "and required columns, then try again."
            )
        }), 500

    finally:
        connection.close()


# ==========================================
# START APPLICATION
# ==========================================

if __name__ == "__main__":
    initialize_database()
    seed_products()

    app.run(debug=True)
