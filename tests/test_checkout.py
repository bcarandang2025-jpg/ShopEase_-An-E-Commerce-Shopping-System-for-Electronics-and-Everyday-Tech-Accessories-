import unittest


def validate_checkout(name, email, items):

    if not name or not name.strip():
        return False

    if not email or "@" not in email:
        return False

    if not isinstance(items, list) or not items:
        return False

    for item in items:

        if "product_id" not in item:
            return False

        if "quantity" not in item:
            return False

        try:
            product_id = int(item["product_id"])
            quantity = int(item["quantity"])
        except (ValueError, TypeError):
            return False

        if product_id <= 0 or quantity <= 0:
            return False

    return True


class CheckoutValidationTests(unittest.TestCase):

    def test_valid_checkout(self):

        result = validate_checkout(
            "Juan",
            "juan@example.com",
            [{"product_id": 1, "quantity": 2}]
        )

        self.assertTrue(result)

    def test_empty_name(self):

        result = validate_checkout(
            "",
            "juan@example.com",
            [{"product_id": 1, "quantity": 2}]
        )

        self.assertFalse(result)

    def test_invalid_email(self):

        result = validate_checkout(
            "Juan",
            "invalid-email",
            [{"product_id": 1, "quantity": 2}]
        )

        self.assertFalse(result)

    def test_empty_cart(self):

        result = validate_checkout(
            "Juan",
            "juan@example.com",
            []
        )

        self.assertFalse(result)

    def test_invalid_quantity(self):

        result = validate_checkout(
            "Juan",
            "juan@example.com",
            [{"product_id": 1, "quantity": 0}]
        )

        self.assertFalse(result)

    def test_invalid_product_id(self):

        result = validate_checkout(
            "Juan",
            "juan@example.com",
            [{"product_id": -1, "quantity": 1}]
        )

        self.assertFalse(result)

    def test_missing_quantity(self):

        result = validate_checkout(
            "Juan",
            "juan@example.com",
            [{"product_id": 1}]
        )

        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()