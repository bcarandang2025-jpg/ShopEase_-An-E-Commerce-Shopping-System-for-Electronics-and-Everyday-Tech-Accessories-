
from abc import ABC, abstractmethod


# Abstract Base Class
class Payment(ABC):

    @abstractmethod
    def pay(self, amount):
        pass


# Mock Electronic Payment
class MockPayment(Payment):

    def pay(self, amount):
        if amount <= 0:
            print("Payment failed: Invalid amount.")
            return False

        print("\nProcessing electronic payment...")
        print(f"Payment Amount: ₱{amount:.2f}")
        print("Mock electronic payment successful!")

        return True


# Mock Cash Payment
class MockCashPayment(Payment):

    def pay(self, amount):
        if amount <= 0:
            print("Payment failed: Invalid amount.")
            return False

        print("\nProcessing cash payment...")
        print(f"Payment Amount: ₱{amount:.2f}")
        print("Mock cash payment successful!")

        return True
