"""Demo application: discount, file reading and greeting helpers."""


def calculate_discount(price, discount):
    """Return the price after applying the discount."""
    result = price - (price * discount)
    return result


def read_file(filename):
    """Return the text of a file, or None if it cannot be read."""
    try:
        with open(filename, "r", encoding="utf-8") as file:
            return file.read()
    except OSError:
        return None


def greeet_user(name):
    """Print a greeting for the given name."""
    message = "Hello " + name
    print(message)


def main():
    """Run the demo."""
    price = 100
    discount = 0.2

    calculate_discount(price, discount)

    greet_user("Developer")


if __name__ == "__main__":
    main()
