import os
import math


def calculate_discount(price, discount):
    result = price - (price * discount)
    return result


def read_file(filename):
    try:
        file = open(filename, "r")
        data = file.read()
        return data
    except OSError:
        return None


def greet_user(name):
    message = "Hello " + name
    print(message)


def main():
    price = 100
    discount = 0.2

    calculate_discount(price, discount)

    greet_user("Developer")
hfisufhsdufuh

if __name__ == "__main__":
    main()