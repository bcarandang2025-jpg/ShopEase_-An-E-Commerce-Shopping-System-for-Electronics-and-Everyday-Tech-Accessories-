
class Customer:
    def __init__(self, name, email, phone=""):
        self.name = name
        self.__email = email
        self.phone = phone

    @property
    def email(self):
        return self.__email

    def update_email(self, new_email):
        if "@" not in new_email or "." not in new_email:
            raise ValueError("Please enter a valid email address.")

        self.__email = new_email
