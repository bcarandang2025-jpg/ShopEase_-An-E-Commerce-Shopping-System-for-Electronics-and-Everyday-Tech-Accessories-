import os
import sqlite3
import qrcode
import base64
import secrets

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
    submit_product_review,
    view_product_reviews,
    get_product_rating_summary,
    get_review_for_order_product,
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
    normalized = {}

    for item in items:
        product_id = int(item["id"])
        quantity = int(item["quantity"])

        normalized[product_id] = (
            normalized.get(product_id, 0) + quantity
        )

    return tuple(sorted(normalized.items()))


# ==========================================
# PUBLIC ORDER ID GENERATOR
# ==========================================

def generate_public_order_id(connection):
    """
    Generates a unique public Order ID.

    Example:
        SE-A83F91C2D4
    """

    order_columns = get_columns(connection, "orders")

    if "public_order_id" not in order_columns:
        raise RuntimeError(
            "public_order_id is missing. Initialize the database first."
        )

    for _ in range(20):
        public_id = "SE-" + secrets.token_hex(5).upper()

        existing = connection.execute(
            """
            SELECT 1
            FROM orders
            WHERE public_order_id = ?
            LIMIT 1
            """,
            (public_id,)
        ).fetchone()

        if not existing:
            return public_id

    raise RuntimeError("Unable to generate a unique Order ID.")


# ==========================================
# PUBLIC ORDER ID DATABASE MIGRATION
# ==========================================

def initialize_public_order_ids():
    """
    Adds public_order_id to the orders table,
    fills existing orders, and creates a unique index.
    """

    connection = get_connection()

    try:
        with connection:

            order_columns = get_columns(connection, "orders")

            order_id_column = find_column(
                order_columns, "order_id", "id"
            )

            if not order_id_column:
                raise RuntimeError(
                    "Orders table has no order ID column."
                )

            if "public_order_id" not in order_columns:
                connection.execute(
                    """
                    ALTER TABLE orders
                    ADD COLUMN public_order_id TEXT
                    """
                )

            order_id_sql = quote_identifier(order_id_column)

            rows = connection.execute(
                f"""
                SELECT {order_id_sql} AS internal_id
                FROM orders
                WHERE public_order_id IS NULL
                   OR public_order_id = ''
                """
            ).fetchall()

            for row in rows:
                public_id = generate_public_order_id(connection)

                connection.execute(
                    f"""
                    UPDATE orders
                    SET public_order_id = ?
                    WHERE {order_id_sql} = ?
                    """,
                    (public_id, row["internal_id"])
                )

            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS
                idx_orders_public_order_id
                ON orders(public_order_id)
                """
            )

    finally:
        connection.close()


# ==========================================
# ORDER SIGNATURE / DUPLICATE HELPERS
# ==========================================

def get_order_signature(connection, order_id):

    columns = get_columns(connection, "order_items")

    order_column = find_column(columns, "order_id")
    product_column = find_column(columns, "product_id")
    quantity_column = find_column(columns, "quantity")

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

    return normalize_items([
        {
            "id": int(row["product_id"]),
            "quantity": int(row["quantity"]),
        }
        for row in rows
    ])


def get_recent_order_ids(connection):

    columns = get_columns(connection, "orders")

    order_id_column = find_column(
        columns, "order_id", "id"
    )

    created_column = find_column(
        columns, "created_at"
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


def find_checkout_duplicate(connection, email, cart_signature):

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
        customer_email_column
    ]):
        return None

    rows = connection.execute(
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

    for row in rows:

        previous_signature = get_order_signature(
            connection, row["order_id"]
        )

        if previous_signature == cart_signature:
            return row["order_id"]

    return None


def get_public_order_id(connection, internal_order_id):

    columns = get_columns(connection, "orders")

    order_id_column = find_column(
        columns, "order_id", "id"
    )

    if not order_id_column or "public_order_id" not in columns:
        return None

    row = connection.execute(
        f"""
        SELECT public_order_id
        FROM orders
        WHERE {quote_identifier(order_id_column)} = ?
        LIMIT 1
        """,
        (internal_order_id,)
    ).fetchone()

    return row["public_order_id"] if row else None


# ==========================================
# ORDER TRACKING / REVIEW HELPERS
# ==========================================

def get_order_items_for_tracking(connection, order_id):

    item_columns = get_columns(connection, "order_items")
    product_columns = get_columns(connection, "products")

    order_column = find_column(item_columns, "order_id")
    item_product_column = find_column(item_columns, "product_id")
    quantity_column = find_column(item_columns, "quantity")

    product_id_column = find_column(
        product_columns, "product_id", "id"
    )

    if not all([
        order_column,
        item_product_column,
        quantity_column,
        product_id_column,
        "name" in product_columns
    ]):
        return []

    rows = connection.execute(
        f"""
        SELECT
            oi.{quote_identifier(item_product_column)} AS product_id,
            oi.{quote_identifier(quantity_column)} AS quantity,
            p.name AS product_name
        FROM order_items oi
        JOIN products p
            ON p.{quote_identifier(product_id_column)}
            = oi.{quote_identifier(item_product_column)}
        WHERE oi.{quote_identifier(order_column)} = ?
        ORDER BY p.name
        """,
        (order_id,)
    ).fetchall()

    result = []

    for row in rows:

        existing_review = get_review_for_order_product(
            order_id, row["product_id"]
        )

        result.append({
            "product_id": row["product_id"],
            "product_name": row["product_name"],
            "quantity": row["quantity"],
            "reviewed": bool(existing_review),
        })

    return result


def get_customer_name(connection, customer_id):

    columns = get_columns(connection, "customers")

    id_column = find_column(
        columns, "customer_id", "id"
    )

    if (
        not id_column
        or "name" not in columns
        or customer_id is None
    ):
        return "Guest"

    row = connection.execute(
        f"""
        SELECT name
        FROM customers
        WHERE {quote_identifier(id_column)} = ?
        LIMIT 1
        """,
        (customer_id,)
    ).fetchone()

    return row["name"] if row else "Guest"


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

    encoded = base64.b64encode(
        buffer.getvalue()
    ).decode("utf-8")

    return f"data:image/png;base64,{encoded}"


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

            flash("Welcome to ShopEase Admin!", "success")

            return redirect(url_for("order_dashboard"))

        flash("Invalid username or password.", "error")

    return render_template("admin_login.html")


@app.route("/admin/logout", methods=["POST"])
@admin_required
def admin_logout():

    session.clear()

    flash("You have been logged out successfully.", "success")

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
            columns, "product_id", "id"
        )

        if not product_id_column:
            raise RuntimeError(
                "The products table has no product ID column."
            )

        if not {"name", "price", "stock"}.issubset(columns):
            raise RuntimeError(
                "Products table must contain name, price, and stock."
            )

        description_sql = (
            quote_identifier("description")
            if "description" in columns
            else "''"
        )

        id_sql = quote_identifier(product_id_column)

        products = connection.execute(
            f"""
            SELECT
                {id_sql} AS id,
                {id_sql} AS product_id,
                name,
                {description_sql} AS description,
                price,
                stock
            FROM products
            ORDER BY {id_sql}
            """
        ).fetchall()

        products = [row_to_dict(row) for row in products]

        return render_template(
            "index.html",
            products=products
        )

    except (
        sqlite3.Error,
        RuntimeError,
        TypeError
    ):

        app.logger.exception("Unable to load product catalog")

        return "Unable to load products. Check your database.", 500

    finally:
        connection.close()


# ==========================================
# SHOPPING CART
# ==========================================

@app.route("/cart")
def cart_page():
    return render_template("cart.html")


# ==========================================
# MANUAL ORDER TRACKING
# ==========================================

@app.route("/track-order", methods=["GET", "POST"])
def track_order():

    error = None

    if request.method == "POST":

        public_order_id = request.form.get(
            "order_id", ""
        ).strip().upper()

        email = request.form.get(
            "email", ""
        ).strip().lower()

        if not public_order_id or not email:

            error = "Please enter your Order ID and email address."

        else:

            connection = get_connection()

            try:

                order_columns = get_columns(
                    connection, "orders"
                )

                customer_columns = get_columns(
                    connection, "customers"
                )

                order_id_column = find_column(
                    order_columns, "order_id", "id"
                )

                order_customer_column = find_column(
                    order_columns, "customer_id"
                )

                customer_id_column = find_column(
                    customer_columns, "customer_id", "id"
                )

                email_column = find_column(
                    customer_columns, "email"
                )

                required = [
                    order_id_column,
                    order_customer_column,
                    customer_id_column,
                    email_column,
                    "public_order_id",
                    "tracking_token"
                ]

                if not all(required):

                    error = (
                        "Manual tracking is unavailable. "
                        "Database structure is incomplete."
                    )

                else:

                    order = connection.execute(
                        f"""
                        SELECT
                            o.{quote_identifier(order_id_column)} AS order_id,
                            o.public_order_id,
                            o.tracking_token
                        FROM orders o
                        JOIN customers c
                            ON c.{quote_identifier(customer_id_column)}
                            = o.{quote_identifier(order_customer_column)}
                        WHERE upper(o.public_order_id) = ?
                          AND lower(c.{quote_identifier(email_column)}) = ?
                        LIMIT 1
                        """,
                        (public_order_id, email)
                    ).fetchone()

                    if order and order["tracking_token"]:

                        return redirect(
                            url_for(
                                "track_order_private",
                                token=order["tracking_token"]
                            )
                        )

                    error = (
                        "Order not found. Please check "
                        "your Order ID and email address."
                    )

            except sqlite3.Error:

                app.logger.exception("Manual tracking failed")

                error = "Unable to find your order right now."

            finally:
                connection.close()

    return render_template(
        "tracking.html",
        order=None,
        order_id="",
        token=None,
        order_items=[],
        error=error
    )


# ==========================================
# PRIVATE QR TRACKING
# ==========================================

@app.route("/track-order/<token>")
def track_order_private(token):

    connection = get_connection()

    try:

        columns = get_columns(connection, "orders")

        order_id_column = find_column(
            columns, "order_id", "id"
        )

        total_column = find_column(
            columns, "total", "total_amount"
        )

        customer_id_column = find_column(
            columns, "customer_id"
        )

        public_id_column = find_column(
            columns, "public_order_id"
        )

        if not all([
            "tracking_token" in columns,
            order_id_column,
            total_column,
            customer_id_column,
            public_id_column,
            "delivery_status" in columns
        ]):

            return render_template(
                "tracking.html",
                order=None,
                order_id="",
                token=None,
                order_items=[],
                error="Tracking information is unavailable."
            )

        status_sql = (
            quote_identifier("status")
            if "status" in columns
            else "'Completed (Mock)'"
        )

        created_sql = (
            quote_identifier("created_at")
            if "created_at" in columns
            else "NULL"
        )

        order = connection.execute(
            f"""
            SELECT
                o.{quote_identifier(order_id_column)} AS order_id,
                o.{quote_identifier(public_id_column)} AS public_order_id,
                o.{quote_identifier(total_column)} AS total,
                o.{status_sql} AS status,
                o.delivery_status AS delivery_status,
                o.{created_sql} AS created_at,
                o.{quote_identifier(customer_id_column)} AS customer_id
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
                token=None,
                order_items=[],
                error="Invalid or unavailable tracking link."
            )

        order_dict = row_to_dict(order)

        order_dict["customer_name"] = get_customer_name(
            connection, order["customer_id"]
        )

        order_items = get_order_items_for_tracking(
            connection, order["order_id"]
        )

        return render_template(
            "tracking.html",
            order=order_dict,
            order_id=order["public_order_id"],
            token=token,
            order_items=order_items,
            error=None
        )

    except (
        sqlite3.Error,
        RuntimeError,
        TypeError,
        ValueError
    ):

        app.logger.exception("Private tracking failed")

        return render_template(
            "tracking.html",
            order=None,
            order_id="",
            token=None,
            order_items=[],
            error="Unable to load your order right now."
        ), 500

    finally:
        connection.close()


# ==========================================
# CUSTOMER PRODUCT REVIEW
# ==========================================

@app.route(
    "/review/<token>/<int:product_id>",
    methods=["GET", "POST"]
)
def submit_review_page(token, product_id):

    connection = get_connection()

    try:

        order_columns = get_columns(
            connection, "orders"
        )

        product_columns = get_columns(
            connection, "products"
        )

        item_columns = get_columns(
            connection, "order_items"
        )

        order_id_column = find_column(
            order_columns, "order_id", "id"
        )

        customer_id_column = find_column(
            order_columns, "customer_id"
        )

        product_id_column = find_column(
            product_columns, "product_id", "id"
        )

        item_order_column = find_column(
            item_columns, "order_id"
        )

        item_product_column = find_column(
            item_columns, "product_id"
        )

        if not all([
            order_id_column,
            customer_id_column,
            product_id_column,
            item_order_column,
            item_product_column,
            "tracking_token" in order_columns,
            "delivery_status" in order_columns
        ]):

            return "Review database structure is incomplete.", 500

        order = connection.execute(
            f"""
            SELECT
                {quote_identifier(order_id_column)} AS order_id,
                {quote_identifier(customer_id_column)} AS customer_id,
                delivery_status,
                tracking_token
            FROM orders
            WHERE tracking_token = ?
            LIMIT 1
            """,
            (token,)
        ).fetchone()

        if not order:
            return "Invalid or unavailable tracking link.", 404

        if str(order["delivery_status"]).lower() != "delivered":

            flash(
                "You can only review products from delivered orders.",
                "error"
            )

            return redirect(
                url_for("track_order_private", token=token)
            )

        order_id = order["order_id"]
        customer_id = order["customer_id"]

        purchased = connection.execute(
            f"""
            SELECT 1
            FROM order_items
            WHERE {quote_identifier(item_order_column)} = ?
              AND {quote_identifier(item_product_column)} = ?
            LIMIT 1
            """,
            (order_id, product_id)
        ).fetchone()

        if not purchased:
            return "This product was not part of this order.", 403

        product = connection.execute(
            f"""
            SELECT
                {quote_identifier(product_id_column)} AS product_id,
                name,
                price
            FROM products
            WHERE {quote_identifier(product_id_column)} = ?
            LIMIT 1
            """,
            (product_id,)
        ).fetchone()

        if not product:
            return "Product not found.", 404

        existing_review = get_review_for_order_product(
            order_id, product_id
        )

        if existing_review:

            flash(
                "You have already reviewed this product.",
                "error"
            )

            return redirect(
                url_for("track_order_private", token=token)
            )

        if request.method == "POST":

            rating = request.form.get("rating", "")
            comment = request.form.get("comment", "")

            success, message = submit_product_review(
                order_id=order_id,
                customer_id=customer_id,
                product_id=product_id,
                rating=rating,
                comment=comment
            )

            if success:

                flash(message, "success")

                return redirect(
                    url_for("track_order_private", token=token)
                )

            flash(message, "error")

        return render_template(
            "review_form.html",
            product=product,
            order_id=order_id,
            token=token
        )

    except (
        sqlite3.Error,
        RuntimeError,
        TypeError,
        ValueError
    ):

        app.logger.exception("Review page failed")

        return "Unable to load the review form.", 500

    finally:
        connection.close()


# ==========================================
# VIEW PRODUCT REVIEWS
# ==========================================

@app.route("/product/<int:product_id>/reviews")
def product_reviews_page(product_id):

    connection = get_connection()

    try:

        columns = get_columns(connection, "products")

        product_id_column = find_column(
            columns, "product_id", "id"
        )

        if not product_id_column:
            return "Product database structure is incomplete.", 500

        product = connection.execute(
            f"""
            SELECT
                {quote_identifier(product_id_column)} AS product_id,
                name,
                price
            FROM products
            WHERE {quote_identifier(product_id_column)} = ?
            """,
            (product_id,)
        ).fetchone()

        if not product:
            return "Product not found.", 404

        product = row_to_dict(product)

    finally:
        connection.close()

    reviews = view_product_reviews(product_id)

    rating_summary = get_product_rating_summary(product_id)

    return render_template(
        "reviews.html",
        product=product,
        reviews=reviews,
        rating_summary=rating_summary
    )
# ==========================================
# ADMIN CUSTOMER REVIEWS & RATINGS
# ==========================================

@app.route("/admin/reviews")
@admin_required
def admin_reviews():

    connection = get_connection()

    try:

        columns = get_columns(connection, "products")

        product_id_column = find_column(
            columns, "product_id", "id"
        )

        if not product_id_column or "name" not in columns:
            raise RuntimeError(
                "Products table is missing required columns."
            )

        products = connection.execute(
            f"""
            SELECT
                {quote_identifier(product_id_column)} AS product_id,
                name
            FROM products
            ORDER BY name
            """
        ).fetchall()

        products = [
            row_to_dict(product)
            for product in products
        ]

    except (
        sqlite3.Error,
        RuntimeError,
        TypeError
    ):

        app.logger.exception(
            "Unable to load admin reviews page"
        )

        flash(
            "Unable to load products for reviews.",
            "error"
        )

        return redirect(url_for("order_dashboard"))

    finally:
        connection.close()

    all_reviews = []
    product_rating_data = []

    total_reviews = 0
    total_rating_points = 0

    for product in products:

        product_id = product["product_id"]

        reviews = view_product_reviews(product_id)

        rating_summary = get_product_rating_summary(
            product_id
        )

        product_review_count = len(reviews)

        # ----------------------------------
        # PRODUCT RATING SUMMARY
        # ----------------------------------

        product_rating_data.append({
            "product_id": product_id,
            "product_name": product["name"],
            "rating_summary": rating_summary,
            "review_count": product_review_count
        })

        # ----------------------------------
        # COLLECT ALL CUSTOMER REVIEWS
        # ----------------------------------

        for review in reviews:

            if isinstance(review, sqlite3.Row):
                review = dict(review)

            elif not isinstance(review, dict):
                continue

            review["product_name"] = product["name"]

            all_reviews.append(review)

        total_reviews += product_review_count

    # ----------------------------------
    # SORT REVIEWS
    # ----------------------------------

    all_reviews.sort(
        key=lambda review: str(
            review.get("created_at", "")
        ),
        reverse=True
    )

    return render_template(
        "admin_reviews.html",
        reviews=all_reviews,
        products=product_rating_data,
        total_reviews=total_reviews
    )

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

        columns = get_columns(connection, "orders")

        order_id_column = find_column(
            columns, "order_id", "id"
        )

        if "public_order_id" in columns and order_id_column:

            id_sql = quote_identifier(order_id_column)

            for order in orders:

                internal_id = get_order_id(order)

                row = connection.execute(
                    f"""
                    SELECT public_order_id
                    FROM orders
                    WHERE {id_sql} = ?
                    """,
                    (internal_id,)
                ).fetchone()

                order["public_order_id"] = (
                    row["public_order_id"] if row else None
                )

        duplicate_map = detect_dashboard_duplicates(
            connection, orders
        )

        for order in orders:

            order_id = get_order_id(order)

            duplicate_info = duplicate_map.get(
                order_id,
                {
                    "duplicate": False,
                    "duplicate_of": None
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

        app.logger.exception("Order dashboard failed")

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
        "cancelled": 0
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
# UPDATE DELIVERY STATUS
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

        flash("Invalid delivery status.", "error")

        return redirect(url_for("order_dashboard"))

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

        app.logger.exception("Status update failed")

        flash("Unable to update delivery status.", "error")

    return redirect(url_for("order_dashboard"))


# ==========================================
# ADMIN PRODUCT RESTOCKING
# ==========================================

@app.route("/admin/restock", methods=["GET", "POST"])
@admin_required
def restock_products():

    connection = get_connection()

    try:

        columns = get_columns(connection, "products")

        product_id_column = find_column(
            columns, "product_id", "id"
        )

        if (
            not product_id_column
            or not {"name", "price", "stock"}.issubset(columns)
        ):

            raise RuntimeError(
                "Products table must contain ID, name, price, and stock."
            )

        id_sql = quote_identifier(product_id_column)

        if request.method == "POST":

            product_id_text = request.form.get(
                "product_id", ""
            ).strip()

            quantity_text = request.form.get(
                "quantity", ""
            ).strip()

            try:

                product_id = int(product_id_text)
                quantity = int(quantity_text)

                if product_id <= 0 or quantity <= 0:
                    raise ValueError

            except (ValueError, TypeError):

                flash(
                    "Select a product and enter a positive quantity.",
                    "error"
                )

                return redirect(url_for("restock_products"))

            with connection:

                result = connection.execute(
                    f"""
                    UPDATE products
                    SET stock = stock + ?
                    WHERE {id_sql} = ?
                    """,
                    (quantity, product_id)
                )

                if result.rowcount != 1:

                    flash("Product not found.", "error")

                else:

                    product = connection.execute(
                        f"""
                        SELECT name, stock
                        FROM products
                        WHERE {id_sql} = ?
                        """,
                        (product_id,)
                    ).fetchone()

                    flash(
                        f"Restocked {product['name']} by {quantity} units. "
                        f"New stock: {product['stock']}.",
                        "success"
                    )

            return redirect(url_for("restock_products"))

        products = connection.execute(
            f"""
            SELECT
                {id_sql} AS id,
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

        app.logger.exception("Restocking failed")

        flash("Unable to load or update inventory.", "error")

        return redirect(url_for("order_dashboard"))

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

    name = str(data.get("name", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    phone = str(data.get("phone", "")).strip()

    items = data.get("items", [])

    # ----------------------------------
    # VALIDATE CUSTOMER
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
    # VALIDATE CART
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

    cart_signature = normalize_items([
        {
            "id": product_id,
            "quantity": quantity
        }
        for product_id, quantity in quantities.items()
    ])

    connection = get_connection()

    try:

        with connection:

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

            required = [
                product_id_column,
                customer_id_column,
                order_customer_column,
                order_total_column,
                item_order_id_column,
                item_product_id_column,
                item_quantity_column,
                item_price_column,
                "public_order_id",
                "tracking_token"
            ]

            if not all(required):

                raise RuntimeError(
                    "A required database column is missing. "
                    "Initialize the database and Order ID migration."
                )

            if not {"name", "price", "stock"}.issubset(
                product_columns
            ):

                raise RuntimeError(
                    "Products table needs name, price, and stock."
                )

            if not {"name", "email"}.issubset(
                customer_columns
            ):

                raise RuntimeError(
                    "Customers table needs name and email."
                )

            # ----------------------------------
            # DUPLICATE ORDER CHECK
            # ----------------------------------

            duplicate_order_id = find_checkout_duplicate(
                connection, email, cart_signature
            )

            if duplicate_order_id:

                duplicate_public_id = get_public_order_id(
                    connection, duplicate_order_id
                )

                return jsonify({
                    "error": (
                        "Duplicate order detected! You already placed "
                        "the same order recently "
                        f"({duplicate_public_id or 'previous order'}). "
                        "Please wait before submitting it again."
                    ),
                    "duplicate": True,
                    "duplicate_order_id": duplicate_public_id
                }), 409

            # ----------------------------------
            # VALIDATE PRODUCTS / STOCK
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

                subtotal = round(price * quantity, 2)

                total += subtotal

                checked_items.append({
                    "id": product_id,
                    "name": product["name"],
                    "quantity": quantity,
                    "price": price,
                    "subtotal": subtotal
                })

            total = round(total, 2)

            if total <= 0:
                raise ValueError("Order total must be greater than zero.")

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
                        values
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
            # GENERATE PUBLIC ID / TOKEN
            # ----------------------------------

            public_order_id = generate_public_order_id(
                connection
            )

            tracking_token = secrets.token_urlsafe(32)

            # ----------------------------------
            # CREATE ORDER
            # ----------------------------------

            order_insert_columns = [
                order_customer_column,
                order_total_column,
                "public_order_id",
                "tracking_token"
            ]

            order_values = [
                customer_id,
                total,
                public_order_id,
                tracking_token
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
                order_values
            )

            order_id = cursor.lastrowid

            # ----------------------------------
            # SAVE ITEMS / UPDATE INVENTORY
            # ----------------------------------

            for item in checked_items:

                item_insert_columns = [
                    item_order_id_column,
                    item_product_id_column,
                    item_quantity_column,
                    item_price_column
                ]

                item_values = [
                    order_id,
                    item["id"],
                    item["quantity"],
                    item["price"]
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
                        item["quantity"]
                    )
                )

                if result.rowcount != 1:

                    raise ValueError(
                        f"Unable to update stock for {item['name']}."
                    )

        # ----------------------------------
        # TRANSACTION COMMITTED
        # ----------------------------------

        tracking_url = url_for(
            "track_order_private",
            token=tracking_token,
            _external=True
        )

        qr_code = generate_tracking_qr(
            tracking_token
        )

        return jsonify({
            "message": "Order placed successfully!",
            "order_id": public_order_id,
            "public_order_id": public_order_id,
            "internal_order_id": order_id,
            "total": total,
            "status": "Completed (Mock)",
            "delivery_status": "Processing",
            "tracking_url": tracking_url,
            "qr_url": qr_code,
            "qr_code": qr_code
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

        app.logger.exception("Checkout failed")

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

    initialize_public_order_ids()

    seed_products()

    app.run(debug=True)