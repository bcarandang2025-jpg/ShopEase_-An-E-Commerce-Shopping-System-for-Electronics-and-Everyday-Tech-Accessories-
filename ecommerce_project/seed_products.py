
from database import get_connection, initialize_database


def seed_products():
    initialize_database()
    connection = get_connection()

    products = [
        ("Wireless Mouse", "Comfortable wireless mouse", 350.00, 10),
        ("USB Keyboard", "Standard USB keyboard", 650.00, 5),
        ("Headphones", "Wired stereo headphones", 499.00, 8),
        ("USB Flash Drive", "32GB USB flash drive", 250.00, 15),
        ("Laptop Stand", "Adjustable laptop stand", 799.00, 4),
    ]

    connection.executemany(
        """
        INSERT INTO products (name, description, price, stock)
        VALUES (?, ?, ?, ?)
        """,
        products
    )

    connection.commit()
    connection.close()

    print("Sample products added successfully!")


if __name__ == "__main__":
    seed_products()
