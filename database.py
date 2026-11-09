
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


# ==========================================
# CREATE TABLES AND UPDATE EXISTING DATABASE
# ==========================================

def initialize_database():
    connection = get_connection()

    try:
        # Create the standard tables if they do not exist.
        # Existing tables and records are preserved.
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

        # Support either total or total_amount.
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

        connection.commit()

        print("Database tables checked successfully!")
        print(f"Product ID column: {product_id_column}")
        print(f"Customer ID column: {customer_id_column}")
        print(f"Order ID column: {order_id_column}")
        print("Order delivery tracking is ready!")

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
                f'"{column}"' for column in insert_columns
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
        customer_id = find_column(
            order_columns, "customer_id", "customer_id"
        )
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
