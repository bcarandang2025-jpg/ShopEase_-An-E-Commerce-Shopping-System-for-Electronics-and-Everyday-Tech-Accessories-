import os
import sqlite3
import qrcode
import base64
import secrets
import json

from io import BytesIO
from functools import wraps

from flask import (
    Flask, render_template, request, jsonify,
    redirect, url_for, flash, session
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
    "local-development-key-change-before-deployment"
)

ADMIN_USERNAME = os.environ.get(
    "SHOPEASE_ADMIN_USERNAME", "admin"
)

ADMIN_PASSWORD = os.environ.get(
    "SHOPEASE_ADMIN_PASSWORD", "ChangeMe123!"
)

DUPLICATE_WINDOW_MINUTES = 5

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
    rows = connection.execute(
        f'PRAGMA table_info("{table}")'
    ).fetchall()

    return {
        row["name"] if isinstance(row, sqlite3.Row) else row[1]
        for row in rows
    }


def find_column(columns, *names):
    for name in names:
        if name in columns:
            return name
    return None


def quote_identifier(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def row_to_dict(row):
    if row is None:
        return None

    if isinstance(row, sqlite3.Row):
        return dict(row)

    if isinstance(row, dict):
        return row

    raise TypeError("Unsupported database record.")


def get_order_id(order):
    return order.get("order_id") or order.get("id", "")


def get_order_total(order):
    return order.get("total") or order.get("total_amount", 0)


def normalize_items(items):
    """
    Create a consistent order signature.
    Example: [{"id": 1, "quantity": 2}]
    """

    normalized = {}

    for item in items:
        product_id = int(item["id"])
        quantity = int(item["quantity"])

        normalized[product_id] = (
            normalized.get(product_id, 0) + quantity
        )

    return tuple(sorted(normalized.items()))


def get_order_signature(connection, order_id):
    """
    Return a consistent product/quantity signature
    for an existing order.
    """

    item_columns = get_columns(connection, "order_items")

    order_column = find_column(
        item_columns, "order_id"
    )

    product_column = find_column(
        item_columns, "product_id"
    )

    quantity_column = find_column(
        item_columns, "quantity"
    )

    if not all([
        order_column,
        product_column,
        quantity_column
    ]):
        return None

    rows = connection.execute(
        f"""
        SELECT
            {quote_identifier(product_column)} AS product_id,
            {quote_identifier(quantity_column)} AS quantity
        FROM order_items
        WHERE {quote_identifier(order_column)} = ?
        """,
        (order_id,)
    ).fetchall()

    if not rows:
        return None

    items = [
        {
            "id": int(row["product_id"]),
            "quantity": int(row["quantity"]),
        }
        for row in rows
    ]

    return normalize_items(items)


def get_recent_order_ids(connection):
    """
    Retrieve orders placed within the duplicate window.
    """

    order_columns = get_columns(connection, "orders")

    order_id_column = find_column(
        order_columns, "order_id", "id"
    )

    created_column = find_column(
        order_columns, "created_at"
    )

    if not order_id_column or not created_column:
        return []

    rows = connection.execute(
        f"""
        SELECT {quote_identifier(order_id_column)} AS order_id
        FROM orders
        WHERE datetime({quote_identifier(created_column)})
              >= datetime('now', '-{DUPLICATE_WINDOW_MINUTES} minutes')
        ORDER BY {quote_identifier(order_id_column)} DESC
        """
    ).fetchall()

    return [row["order_id"] for row in rows]


def detect_dashboard_duplicates(connection, orders):
    """
    Flag matching recent orders on the admin dashboard.

    This detection compares orders across customers.
    """

    signatures = {}
    recent_ids = set(get_recent_order_ids(connection))

    for order in orders:
        order_id = get_order_id(order)

        if order_id not in recent_ids:
            continue

        signature = get_order_signature(
            connection, order_id
        )

        if signature:
            signatures[order_id] = signature

    duplicate_map = {}
    processed = {}

    for order in orders:

        order_id = get_order_id(order)

        signature = signatures.get(order_id)

        if signature is None:
            continue

        if signature in processed:

            duplicate_map[order_id] = {
                "duplicate": True,
                "duplicate_of": processed[signature],
            }

        else:

            processed[signature] = order_id

            duplicate_map[order_id] = {
                "duplicate": False,
                "duplicate_of": None,
            }

    return duplicate_map


def find_checkout_duplicate(
    connection,
    email,
    cart_signature,
):
    """
    Prevent the same customer from submitting
    the exact same cart within five minutes.
    """

    order_columns = get_columns(connection, "orders")
    customer_columns = get_columns(connection, "customers")

    order_id_column = find_column(
        order_columns, "order_id", "id"
    )

    order_customer_column = find_column(
        order_columns, "customer_id"
    )

    created_column = find_column(
        order_columns, "created_at"
    )

    customer_id_column = find_column(
        customer_columns, "customer_id", "id"
    )

    customer_email_column = find_column(
        customer_columns, "email"
    )

    if not all([
        order_id_column,
        order_customer_column,
        created_column,
        customer_id_column,
        customer_email_column,
    ]):
        return None

    recent_orders = connection.execute(
        f"""
        SELECT
            o.{quote_identifier(order_id_column)} AS order_id
        FROM orders o
        JOIN customers c
            ON c.{quote_identifier(customer_id_column)}
            = o.{quote_identifier(order_customer_column)}
        WHERE lower(c.{quote_identifier(customer_email_column)}) = ?
          AND datetime(o.{quote_identifier(created_column)})
              >= datetime('now', '-{DUPLICATE_WINDOW_MINUTES} minutes')
        ORDER BY o.{quote_identifier(order_id_column)} DESC
        """,
        (email.lower(),)
    ).fetchall()

    for row in recent_orders:

        previous_order_id = row["order_id"]

        previous_signature = get_order_signature(
            connection, previous_order_id
        )

        if previous_signature == cart_signature:

            return previous_order_id

    return None


# ==========================================
# QR CODE GENERATOR
# ==========================================

def generate_tracking_qr(token):

    tracking_url = url_for(
        "track_order_private",
        token=token,
        _external=True
    )

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )

    qr.add_data(tracking_url)
    qr.make(fit=True)

    image = qr.make_image(
        fill_color="black",
        back_color="white"
    )

    buffer = BytesIO()
    image.save(buffer, format="PNG")

    qr_base64 = base64.b64encode(
        buffer.getvalue()
    ).decode("utf-8")

    return f"data:image/png;base64,{qr_base64}"


# ==========================================
# ADMIN AUTHENTICATION
# ==========================================

def admin_required(view_function):

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

        columns = get_columns(
            connection, "products"
        )

        product_id_column = find_column(
            columns, "product_id", "id"
        )

        if not product_id_column:
            raise RuntimeError(
                "The products table has no product ID column."
            )

        if not {"name", "price", "stock"}.issubset(columns):
            raise RuntimeError(
                "The products table must contain name, price, and stock."
            )

        description_sql = (
            quote_identifier("description")
            if "description" in columns
            else "''"
        )

        product_id_sql = quote_identifier(
            product_id_column
        )

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

        products = [
            row_to_dict(row)
            for row in products
        ]

        return render_template(
            "index.html",
            products=products
        )

    except (
        sqlite3.Error,
        RuntimeError,
        TypeError
    ):

        app.logger.exception(
            "Unable to load product catalog"
        )

        return (
            "Unable to load products. "
            "Check your database.",
            500
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

    order_id = request.args.get(
        "order_id", ""
    ).strip()

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
                    None
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
                ValueError
            ):

                app.logger.exception(
                    "Order tracking failed"
                )

                error = (
                    "Unable to load your order right now."
                )

    return render_template(
        "tracking.html",
        order=order,
        order_id=order_id,
        error=error
    )


@app.route("/track-order/<token>")
def track_order_private(token):

    connection = get_connection()

    try:

        order_columns = get_columns(
            connection, "orders"
        )

        order_id_column = find_column(
            order_columns, "order_id", "id"
        )

        total_column = find_column(
            order_columns, "total", "total_amount"
        )

        if (
            "tracking_token" not in order_columns
            or not order_id_column
            or not total_column
        ):

            return render_template(
                "tracking.html",
                order=None,
                order_id="",
                error="Tracking information is unavailable."
            )

        order = connection.execute(
            f"""
            SELECT
                o.{quote_identifier(order_id_column)} AS order_id,
                o.{quote_identifier(total_column)} AS total,
                o.status AS status,
                o.delivery_status AS delivery_status,
                o.created_at AS created_at
            FROM orders o
            WHERE o.tracking_token = ?
            LIMIT 1
            """,
            (token,)
        ).fetchone()

        if not order:

            return render_template(
                "tracking.html",
                order=None,
                order_id="",
                error="Invalid or unavailable tracking link."
            )

        return render_template(
            "tracking.html",
            order=order,
            order_id=order["order_id"],
            error=None
        )

    finally:
        connection.close()


# ==========================================
# ADMIN ORDER DASHBOARD
# ==========================================

@app.route("/admin/orders")
@admin_required
def order_dashboard():

    connection = get_connection()

    try:

        orders = [
            row_to_dict(row)
            for row in view_orders()
        ]

        duplicate_map = detect_dashboard_duplicates(
            connection, orders
        )

        # Add duplicate information to each order.
        for order in orders:

            order_id = get_order_id(order)

            duplicate_info = duplicate_map.get(
                order_id,
                {
                    "duplicate": False,
                    "duplicate_of": None,
                }
            )

            order["duplicate"] = duplicate_info["duplicate"]
            order["duplicate_of"] = duplicate_info["duplicate_of"]

    except (
        sqlite3.Error,
        RuntimeError,
        TypeError,
        ValueError
    ):

        app.logger.exception(
            "Could not load order dashboard"
        )

        orders = []

        flash(
            "Unable to load orders. Please check your database.",
            "error"
        )

    finally:
        connection.close()

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
        error=None
    )


# ==========================================
# UPDATE ORDER DELIVERY STATUS
# ==========================================

@app.route(
    "/admin/orders/<int:order_id>/status",
    methods=["POST"]
)
@admin_required
def update_order_status(order_id):

    new_status = request.form.get(
        "delivery_status", ""
    ).strip()

    if new_status not in DELIVERY_STATUSES:

        flash(
            "Invalid delivery status.",
            "error"
        )

        return redirect(
            url_for("order_dashboard")
        )

    try:

        updated = update_delivery_status(
            order_id, new_status
        )

        if updated:

            flash(
                f"Order #{order_id} status updated to {new_status}.",
                "success"
            )

        else:

            flash(
                f"Order #{order_id} was not found.",
                "error"
            )

    except (
        sqlite3.Error,
        ValueError,
        RuntimeError
    ):

        app.logger.exception(
            "Could not update delivery status"
        )

        flash(
            "Unable to update delivery status.",
            "error"
        )

    return redirect(
        url_for("order_dashboard")
    )


# ==========================================
# ADMIN PRODUCT RESTOCKING
# ==========================================

@app.route("/admin/restock", methods=["GET", "POST"])
@admin_required
def restock_products():

    connection = get_connection()

    try:

        product_columns = get_columns(
            connection, "products"
        )

        product_id_column = find_column(
            product_columns, "product_id", "id"
        )

        if (
            not product_id_column
            or not {"name", "price", "stock"}.issubset(product_columns)
        ):

            raise RuntimeError(
                "The products table must contain ID, name, price, and stock."
            )

        product_id_sql = quote_identifier(
            product_id_column
        )

        if request.method == "POST":

            product_id = request.form.get(
                "product_id", ""
            ).strip()

            quantity_text = request.form.get(
                "quantity", ""
            ).strip()

            try:

                product_id = int(product_id)
                quantity = int(quantity_text)

                if product_id <= 0 or quantity <= 0:
                    raise ValueError

            except (ValueError, TypeError):

                flash(
                    "Select a product and enter a positive quantity.",
                    "error"
                )

                return redirect(
                    url_for("restock_products")
                )

            with connection:

                result = connection.execute(
                    f"""
                    UPDATE products
                    SET stock = stock + ?
                    WHERE {product_id_sql} = ?
                    """,
                    (quantity, product_id)
                )

                if result.rowcount != 1:

                    flash(
                        "Product not found.",
                        "error"
                    )

                else:

                    product = connection.execute(
                        f"""
                        SELECT name, stock
                        FROM products
                        WHERE {product_id_sql} = ?
                        """,
                        (product_id,)
                    ).fetchone()

                    flash(
                        f"Restocked {product['name']} by {quantity} units. "
                        f"New stock: {product['stock']}.",
                        "success"
                    )

            return redirect(
                url_for("restock_products")
            )

        products = connection.execute(
            f"""
            SELECT
                {product_id_sql} AS id,
                name,
                price,
                stock
            FROM products
            ORDER BY name
            """
        ).fetchall()

        return render_template(
            "restock.html",
            products=products
        )

    except (
        sqlite3.Error,
        RuntimeError,
        TypeError
    ):

        app.logger.exception(
            "Restock page or inventory update failed"
        )

        flash(
            "Unable to load or update inventory.",
            "error"
        )

        return redirect(
            url_for("order_dashboard")
        )

    finally:
        connection.close()


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

    name = str(
        data.get("name", "")
    ).strip()

    email = str(
        data.get("email", "")
    ).strip().lower()

    phone = str(
        data.get("phone", "")
    ).strip()

    items = data.get("items", [])

    # ----------------------------------
    # VALIDATE CUSTOMER INFORMATION
    # ----------------------------------

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

    # ----------------------------------
    # VALIDATE CART ITEMS
    # ----------------------------------

    if not isinstance(items, list) or not items:

        return jsonify({
            "error": "Your cart is empty."
        }), 400

    quantities = {}

    for item in items:

        if not isinstance(item, dict):

            return jsonify({
                "error": "Invalid cart item."
            }), 400

        product_id = item.get(
            "id", item.get("product_id")
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

    cart_signature = normalize_items(
        [
            {
                "id": product_id,
                "quantity": quantity,
            }
            for product_id, quantity in quantities.items()
        ]
    )

    connection = get_connection()

    try:

        with connection:

            # ----------------------------------
            # DETECT DATABASE COLUMNS
            # ----------------------------------

            product_columns = get_columns(
                connection, "products"
            )

            customer_columns = get_columns(
                connection, "customers"
            )

            order_columns = get_columns(
                connection, "orders"
            )

            item_columns = get_columns(
                connection, "order_items"
            )

            product_id_column = find_column(
                product_columns, "product_id", "id"
            )

            customer_id_column = find_column(
                customer_columns, "customer_id", "id"
            )

            order_customer_column = find_column(
                order_columns, "customer_id"
            )

            order_total_column = find_column(
                order_columns, "total", "total_amount"
            )

            item_order_id_column = find_column(
                item_columns, "order_id"
            )

            item_product_id_column = find_column(
                item_columns, "product_id"
            )

            item_quantity_column = find_column(
                item_columns, "quantity"
            )

            item_price_column = find_column(
                item_columns, "unit_price", "price"
            )

            item_subtotal_column = find_column(
                item_columns, "subtotal"
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
                    "A required database column is missing."
                )

            if not {"name", "price", "stock"}.issubset(
                product_columns
            ):

                raise RuntimeError(
                    "The products table needs name, price, and stock."
                )

            if not {"name", "email"}.issubset(
                customer_columns
            ):

                raise RuntimeError(
                    "The customers table needs name and email."
                )

            # ----------------------------------
            # DUPLICATE CHECK - BEFORE PAYMENT
            # ----------------------------------

            duplicate_order_id = find_checkout_duplicate(
                connection,
                email,
                cart_signature
            )

            if duplicate_order_id:

                return jsonify({
                    "error": (
                        "Duplicate order detected! "
                        f"You already placed the same order recently "
                        f"(Order #{duplicate_order_id}). "
                        "Please wait before submitting it again."
                    ),
                    "duplicate": True,
                    "duplicate_order_id": duplicate_order_id,
                }), 409

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
                    (product_id,)
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

                subtotal = round(
                    price * quantity, 2
                )

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
                WHERE lower(email) = ?
                """,
                (email,)
            ).fetchone()

            if customer:

                customer_id = customer[
                    customer_id_column
                ]

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
                        values
                    )

            else:

                insert_columns = [
                    "name", "email"
                ]

                insert_values = [
                    name, email
                ]

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
                    insert_values
                )

                customer_id = cursor.lastrowid

            # ----------------------------------
            # MOCK PAYMENT
            # ----------------------------------

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

            tracking_token = secrets.token_urlsafe(32)

            if "status" in order_columns:

                order_insert_columns.append("status")
                order_values.append("Completed (Mock)")

            if "delivery_status" in order_columns:

                order_insert_columns.append(
                    "delivery_status"
                )

                order_values.append("Processing")

            if "tracking_token" in order_columns:

                order_insert_columns.append(
                    "tracking_token"
                )

                order_values.append(tracking_token)

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
                order_values
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

                    item_values.append(
                        item["subtotal"]
                    )

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
                    item_values
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
                    )
                )

                if result.rowcount != 1:

                    raise ValueError(
                        f"Unable to update stock for {item['name']}."
                    )

        # ----------------------------------
        # TRANSACTION COMMITTED
        # ----------------------------------

        if tracking_token:

            tracking_url = url_for(
                "track_order_private",
                token=tracking_token,
                _external=True
            )

            qr_code = generate_tracking_qr(
                tracking_token
            )

        else:

            tracking_url = url_for(
                "track_order",
                order_id=order_id,
                _external=True
            )

            qr_code = None

        # ----------------------------------
        # CHECKOUT SUCCESS
        # ----------------------------------

        return jsonify({
            "message": "Order placed successfully!",
            "order_id": order_id,
            "total": total,
            "status": "Completed (Mock)",
            "delivery_status": "Processing",
            "tracking_url": tracking_url,
            "qr_url": qr_code,
            "qr_code": qr_code,
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
        OverflowError
    ):

        app.logger.exception(
            "Checkout failed"
        )

        return jsonify({
            "error": (
                "Checkout failed. Check the database "
                "structure and required columns."
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