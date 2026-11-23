import sqlite3
from pathlib import Path

# ==========================================
# DATABASE CONFIGURATION
# ==========================================

BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "ecommerce.db"

DELIVERY_STATUSES = {
    "Pending",
    "Processing",
    "Shipped",
    "Delivered",
    "Cancelled",
}


def get_connection():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def get_columns(connection, table_name):
    """Return the existing column names of a table."""
    return {
        row["name"]
        for row in connection.execute(
            f'PRAGMA table_info("{table_name}")'
        ).fetchall()
    }


def find_column(columns, *candidates):
    """Find the first matching column name."""
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def quote_identifier(identifier):
    """Safely quote a SQL identifier."""
    return '"' + str(identifier).replace('"', '""') + '"'


# ==========================================
# CREATE TABLES AND UPDATE EXISTING DATABASE
# ==========================================

def initialize_database():
    connection = get_connection()

    try:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS customers (
                customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                phone TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS products (
                product_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                price REAL NOT NULL DEFAULT 0,
                stock INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS orders (
                order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL,
                total REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'Pending',
                delivery_status TEXT NOT NULL DEFAULT 'Processing',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS order_items (
                order_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL CHECK (quantity > 0),
                unit_price REAL NOT NULL DEFAULT 0,
                subtotal REAL NOT NULL DEFAULT 0
            );
        """)

        # ----------------------------------
        # PRODUCTS MIGRATION
        # ----------------------------------

        product_columns = get_columns(connection, "products")

        product_id_column = find_column(
            product_columns, "product_id", "id"
        )

        if not product_id_column:
            raise RuntimeError(
                "The products table needs an 'id' or 'product_id' column."
            )

        if "name" not in product_columns:
            raise RuntimeError(
                "The products table is missing its 'name' column."
            )

        if "description" not in product_columns:
            connection.execute(
                "ALTER TABLE products ADD COLUMN description TEXT"
            )

        if "price" not in product_columns:
            connection.execute("""
                ALTER TABLE products
                ADD COLUMN price REAL NOT NULL DEFAULT 0
            """)

        if "stock" not in product_columns:
            connection.execute("""
                ALTER TABLE products
                ADD COLUMN stock INTEGER NOT NULL DEFAULT 0
            """)

        # ----------------------------------
        # CUSTOMERS MIGRATION
        # ----------------------------------

        customer_columns = get_columns(connection, "customers")

        customer_id_column = find_column(
            customer_columns, "customer_id", "id"
        )

        if not customer_id_column:
            raise RuntimeError(
                "The customers table needs an 'id' or 'customer_id' column."
            )

        if "name" not in customer_columns:
            raise RuntimeError(
                "The customers table is missing its 'name' column."
            )

        # ----------------------------------
        # ORDERS MIGRATION
        # ----------------------------------

        order_columns = get_columns(connection, "orders")

        order_id_column = find_column(
            order_columns, "order_id", "id"
        )

        if not order_id_column:
            raise RuntimeError(
                "The orders table needs an 'id' or 'order_id' column."
            )

        total_column = find_column(
            order_columns, "total", "total_amount"
        )

        if not total_column:
            connection.execute("""
                ALTER TABLE orders
                ADD COLUMN total REAL NOT NULL DEFAULT 0
            """)

        order_columns = get_columns(connection, "orders")

        if "status" not in order_columns:
            connection.execute("""
                ALTER TABLE orders
                ADD COLUMN status TEXT NOT NULL DEFAULT 'Pending'
            """)

        if "delivery_status" not in order_columns:
            connection.execute("""
                ALTER TABLE orders
                ADD COLUMN delivery_status TEXT NOT NULL
                DEFAULT 'Processing'
            """)

        if "created_at" not in order_columns:
            connection.execute("""
                ALTER TABLE orders
                ADD COLUMN created_at TEXT
            """)

        # ----------------------------------
        # PRIVATE ORDER TRACKING TOKEN
        # ----------------------------------

        order_columns = get_columns(connection, "orders")

        if "tracking_token" not in order_columns:
            connection.execute("""
                ALTER TABLE orders
                ADD COLUMN tracking_token TEXT
            """)

        connection.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS
            idx_orders_tracking_token
            ON orders(tracking_token)
        """)

        # ----------------------------------
        # PRODUCT REVIEWS TABLE
        # ----------------------------------

        connection.execute("""
            CREATE TABLE IF NOT EXISTS product_reviews (
                review_id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                customer_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
                comment TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(order_id, product_id)
            )
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_product_reviews_product
            ON product_reviews(product_id)
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_product_reviews_customer
            ON product_reviews(customer_id)
        """)

        connection.commit()

        print("Database tables checked successfully!")
        print(f"Product ID column: {product_id_column}")
        print(f"Customer ID column: {customer_id_column}")
        print(f"Order ID column: {order_id_column}")
        print("Order delivery tracking is ready!")
        print("Product reviews system is ready!")

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


# ==========================================
# INSERT SAMPLE PRODUCTS
# ==========================================

def seed_products():
    products = [
        (
            "Wireless Mouse",
            "Comfortable wireless mouse",
            350.00,
            10,
        ),
        (
            "USB Keyboard",
            "Standard USB keyboard",
            650.00,
            5,
        ),
        (
            "Headphones",
            "Over-ear headphones for everyday use",
            499.00,
            8,
        ),
        (
            "USB Flash Drive",
            "32GB USB flash drive",
            250.00,
            15,
        ),
        (
            "Laptop Stand",
            "Foldable laptop stand for your workspace",
            799.00,
            4,
        ),
    ]

    connection = get_connection()

    try:
        columns = get_columns(connection, "products")
        name_column = find_column(columns, "name")
        description_column = find_column(columns, "description")
        price_column = find_column(columns, "price")
        stock_column = find_column(columns, "stock")

        if not all([name_column, price_column, stock_column]):
            raise RuntimeError(
                "The products table is missing required columns."
            )

        for name, description, price, stock in products:
            existing = connection.execute(
                f'SELECT 1 FROM products WHERE "{name_column}" = ? LIMIT 1',
                (name,),
            ).fetchone()

            if existing:
                continue

            insert_columns = [
                name_column,
                price_column,
                stock_column,
            ]
            values = [name, price, stock]

            if description_column:
                insert_columns.insert(1, description_column)
                values.insert(1, description)

            quoted_columns = ", ".join(
                quote_identifier(column)
                for column in insert_columns
            )
            placeholders = ", ".join("?" for _ in values)

            connection.execute(
                f"""
                INSERT INTO products ({quoted_columns})
                VALUES ({placeholders})
                """,
                values,
            )

        connection.commit()
        print("Sample products added/checked successfully!")

    finally:
        connection.close()


# ==========================================
# VIEW ALL PRODUCTS
# ==========================================

def view_products():
    connection = get_connection()

    try:
        columns = get_columns(connection, "products")
        id_column = find_column(columns, "product_id", "id")

        if not id_column:
            raise RuntimeError("No product ID column was found.")

        required_columns = ["name", "price", "stock"]

        for column in required_columns:
            if column not in columns:
                raise RuntimeError(
                    f"The products table is missing '{column}'."
                )

        description_expression = (
            '"description"' if "description" in columns
            else "''"
        )

        query = f"""
            SELECT
                "{id_column}" AS product_id,
                "name" AS name,
                {description_expression} AS description,
                "price" AS price,
                "stock" AS stock
            FROM products
            ORDER BY "{id_column}"
        """

        return connection.execute(query).fetchall()

    finally:
        connection.close()


# ==========================================
# VIEW ALL ORDERS
# ==========================================

def view_orders():
    connection = get_connection()

    try:
        order_columns = get_columns(connection, "orders")
        customer_columns = get_columns(connection, "customers")

        order_id = find_column(order_columns, "order_id", "id")
        customer_id = find_column(order_columns, "customer_id")
        customer_pk = find_column(
            customer_columns, "customer_id", "id"
        )
        total_column = find_column(
            order_columns, "total", "total_amount"
        )

        if not order_id:
            raise RuntimeError("No order ID column was found.")

        if not total_column:
            raise RuntimeError(
                "The orders table has neither 'total' nor 'total_amount'."
            )

        if customer_id and customer_pk and "name" in customer_columns:
            customer_name = "c.name"
            customer_email = (
                "c.email" if "email" in customer_columns else "''"
            )
            join_clause = (
                f'LEFT JOIN customers c '
                f'ON o."{customer_id}" = c."{customer_pk}"'
            )
        else:
            customer_name = "''"
            customer_email = "''"
            join_clause = ""

        status_expression = (
            "o.delivery_status"
            if "delivery_status" in order_columns
            else "'Processing'"
        )

        payment_expression = (
            "o.status" if "status" in order_columns else "'Pending'"
        )

        created_expression = (
            "o.created_at"
            if "created_at" in order_columns
            else "''"
        )

        query = f"""
            SELECT
                o."{order_id}" AS order_id,
                {customer_name} AS customer_name,
                {customer_email} AS customer_email,
                o."{total_column}" AS total,
                {payment_expression} AS status,
                {status_expression} AS delivery_status,
                {created_expression} AS created_at
            FROM orders o
            {join_clause}
            ORDER BY o."{order_id}" DESC
        """

        return connection.execute(query).fetchall()

    finally:
        connection.close()


# ==========================================
# UPDATE DELIVERY STATUS
# ==========================================

def update_delivery_status(order_id, new_status):
    if new_status not in DELIVERY_STATUSES:
        raise ValueError(
            f"Invalid delivery status. Choose from: "
            f"{', '.join(sorted(DELIVERY_STATUSES))}"
        )

    connection = get_connection()

    try:
        columns = get_columns(connection, "orders")
        id_column = find_column(columns, "order_id", "id")

        if not id_column:
            raise RuntimeError("No order ID column was found.")

        if "delivery_status" not in columns:
            connection.execute("""
                ALTER TABLE orders
                ADD COLUMN delivery_status TEXT NOT NULL
                DEFAULT 'Processing'
            """)

        cursor = connection.execute(
            f'UPDATE orders SET delivery_status = ? '
            f'WHERE "{id_column}" = ?',
            (new_status, order_id),
        )

        connection.commit()
        return cursor.rowcount > 0

    finally:
        connection.close()


# ==========================================
# PRODUCT REVIEW SYSTEM
# ==========================================

def get_review_for_order_product(order_id, product_id):
    """
    Check whether a customer already reviewed
    a product within a particular order.
    """

    connection = get_connection()

    try:
        return connection.execute("""
            SELECT *
            FROM product_reviews
            WHERE order_id = ?
              AND product_id = ?
            LIMIT 1
        """, (order_id, product_id)).fetchone()

    finally:
        connection.close()


def submit_product_review(
    order_id,
    customer_id,
    product_id,
    rating,
    comment
):
    """
    Submit a review for a product from a delivered order.

    Only the customer who owns the delivered order
    can review its products.

    Returns:
        (True, success_message) on success
        (False, error_message) on failure
    """

    # ----------------------------------
    # VALIDATE RATING
    # ----------------------------------

    try:
        rating = int(rating)
    except (TypeError, ValueError):
        return False, "Rating must be a number from 1 to 5."

    if rating < 1 or rating > 5:
        return False, "Rating must be between 1 and 5 stars."

    # ----------------------------------
    # VALIDATE COMMENT
    # ----------------------------------

    if not isinstance(comment, str):
        return False, "Review comment must be text."

    comment = comment.strip()

    if not comment:
        return False, "Please write a review before submitting."

    if len(comment) > 2000:
        return False, "Your review must not exceed 2000 characters."

    connection = get_connection()

    try:
        # ----------------------------------
        # DETECT DATABASE COLUMNS
        # ----------------------------------

        order_columns = get_columns(connection, "orders")
        item_columns = get_columns(connection, "order_items")

        order_id_column = find_column(
            order_columns, "order_id", "id"
        )
        customer_id_column = find_column(
            order_columns, "customer_id"
        )
        delivery_column = find_column(
            order_columns, "delivery_status"
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
            delivery_column,
            item_order_column,
            item_product_column,
        ]):
            return False, "The order database structure is incomplete."

        # ----------------------------------
        # VERIFY ORDER OWNERSHIP AND DELIVERY
        # ----------------------------------

        order = connection.execute(
            f"""
            SELECT *
            FROM orders
            WHERE "{order_id_column}" = ?
              AND "{customer_id_column}" = ?
            """,
            (order_id, customer_id),
        ).fetchone()

        if not order:
            return False, "Order not found or does not belong to you."

        if str(order[delivery_column]).strip().lower() != "delivered":
            return False, "You can only review delivered orders."

        # ----------------------------------
        # VERIFY PRODUCT WAS IN THE ORDER
        # ----------------------------------

        purchased_product = connection.execute(
            f"""
            SELECT 1
            FROM order_items
            WHERE "{item_order_column}" = ?
              AND "{item_product_column}" = ?
            LIMIT 1
            """,
            (order_id, product_id),
        ).fetchone()

        if not purchased_product:
            return False, "This product was not included in your order."

        # ----------------------------------
        # PREVENT DUPLICATE REVIEWS
        # ----------------------------------

        existing_review = connection.execute("""
            SELECT review_id
            FROM product_reviews
            WHERE order_id = ?
              AND product_id = ?
            LIMIT 1
        """, (order_id, product_id)).fetchone()

        if existing_review:
            return False, "You have already reviewed this product in this order."

        # ----------------------------------
        # SAVE REVIEW
        # ----------------------------------

        connection.execute("""
            INSERT INTO product_reviews (
                order_id,
                customer_id,
                product_id,
                rating,
                comment
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            order_id,
            customer_id,
            product_id,
            rating,
            comment,
        ))

        connection.commit()

        return True, "Your product review was submitted successfully!"

    except sqlite3.IntegrityError:
        connection.rollback()
        return False, "You have already reviewed this product in this order."

    except Exception as error:
        connection.rollback()
        return False, f"Unable to submit review: {error}"

    finally:
        connection.close()


# ==========================================
# VIEW PRODUCT REVIEWS
# ==========================================

def view_product_reviews(product_id):
    """
    Retrieve all reviews for a product.

    Returns reviews with customer name,
    rating, comment, date, and order ID.
    """

    connection = get_connection()

    try:
        customer_columns = get_columns(connection, "customers")
        customer_id_column = find_column(
            customer_columns, "customer_id", "id"
        )

        if customer_id_column and "name" in customer_columns:
            customer_join = (
                f'LEFT JOIN customers c '
                f'ON r.customer_id = c."{customer_id_column}"'
            )
            customer_name_expression = "c.name"
        else:
            customer_join = ""
            customer_name_expression = "'Customer'"

        query = f"""
            SELECT
                r.review_id,
                r.order_id,
                r.customer_id,
                r.product_id,
                r.rating,
                r.comment,
                r.created_at,
                {customer_name_expression} AS customer_name
            FROM product_reviews r
            {customer_join}
            WHERE r.product_id = ?
            ORDER BY r.created_at DESC, r.review_id DESC
        """

        return connection.execute(
            query, (product_id,)
        ).fetchall()

    finally:
        connection.close()


# ==========================================
# PRODUCT RATING SUMMARY
# ==========================================

def get_product_rating_summary(product_id):
    """
    Return the average rating and total review count.

    Returns:
        {
            'average_rating': float,
            'total_reviews': int
        }
    """

    connection = get_connection()

    try:
        result = connection.execute("""
            SELECT
                COALESCE(AVG(rating), 0) AS average_rating,
                COUNT(*) AS total_reviews
            FROM product_reviews
            WHERE product_id = ?
        """, (product_id,)).fetchone()

        return {
            "average_rating": round(
                float(result["average_rating"]), 1
            ),
            "total_reviews": int(result["total_reviews"]),
        }

    finally:
        connection.close()


# ==========================================
# VIEW CUSTOMER REVIEW HISTORY
# ==========================================

def view_customer_reviews(customer_id):
    """Retrieve all reviews submitted by a customer."""

    connection = get_connection()

    try:
        product_columns = get_columns(connection, "products")
        product_id_column = find_column(
            product_columns, "product_id", "id"
        )

        if not product_id_column:
            raise RuntimeError(
                "No product ID column was found."
            )

        query = f"""
            SELECT
                r.review_id,
                r.order_id,
                r.customer_id,
                r.product_id,
                r.rating,
                r.comment,
                r.created_at,
                p.name AS product_name
            FROM product_reviews r
            LEFT JOIN products p
                ON r.product_id = p."{product_id_column}"
            WHERE r.customer_id = ?
            ORDER BY r.created_at DESC, r.review_id DESC
        """

        return connection.execute(
            query, (customer_id,)
        ).fetchall()

    finally:
        connection.close()


# ==========================================
# RUN DATABASE FILE
# ==========================================

if __name__ == "__main__":
    initialize_database()
    seed_products()

    print("\nSHOP EASE PRODUCTS")
    print("-" * 60)

    for product in view_products():
        print(
            f"ID: {product['product_id']} | "
            f"{product['name']} | "
            f"Price: PHP {product['price']:.2f} | "
            f"Stock: {product['stock']}"
        )

    print("\nSHOP EASE ORDERS")
    print("-" * 60)

    for order in view_orders():
        print(
            f"Order #{order['order_id']} | "
            f"Customer: {order['customer_name']} | "
            f"Total: PHP {order['total']:.2f} | "
            f"Status: {order['delivery_status']}"
        )

    print("\nSHOP EASE PRODUCT REVIEWS")
    print("-" * 60)

    print("Product review table is ready.")