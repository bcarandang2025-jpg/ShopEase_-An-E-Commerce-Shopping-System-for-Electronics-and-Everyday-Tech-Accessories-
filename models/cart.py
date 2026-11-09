
class Cart:
    def __init__(self):
        self.__items = {}

    def add_product(self, product, quantity=1):
        if not product.is_available(quantity):
            raise ValueError("Insufficient product stock.")

        current_quantity = self.__items.get(product.product_id, 0)
        new_quantity = current_quantity + quantity

        if new_quantity > product.stock:
            raise ValueError("Not enough stock for this quantity.")

        self.__items[product.product_id] = {
            "product": product,
            "quantity": new_quantity
        }

    def remove_product(self, product_id):
        self.__items.pop(product_id, None)

    def get_items(self):
        return list(self.__items.values())

    @property
    def total(self):
        return sum(
            item["product"].price * item["quantity"]
            for item in self.__items.values()
        )

    def clear(self):
        self.__items.clear()
