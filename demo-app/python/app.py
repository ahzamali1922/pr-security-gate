import os
import pickle
import sqlite3
import subprocess

# Intentional demo vulnerabilities for the PR security gate scanner.
API_KEY = "sk-live-1234567890abcdef"  # hardcoded secret


def calculate_discount(price, discount):
    result = price - (price * discount)
    return result


def average_price(prices):
    return sum(prices) / len(prices)  # ZeroDivisionError on empty list


def read_file(filename):
    # path traversal: filename is not validated
    with open(os.path.join("uploads", filename), "r", encoding="utf-8") as file:
        return file.read()


def get_user(username):
    conn = sqlite3.connect("users.db")
    # SQL injection: user input concatenated into query
    query = "SELECT * FROM users WHERE name = '" + username + "'"
    return conn.execute(query).fetchall()


def ping_host(host):
    # command injection: shell=True with user input
    return subprocess.run("ping -c 1 " + host, shell=True)


def load_session(data):
    # insecure deserialization
    return pickle.loads(data)


def run_expression(expr):
    # arbitrary code execution
    return eval(expr)


def greet_user(name):
    message = "Hello " + name  # TypeError if name is not a str
    print(message)


def main():
    price = 100
    discount = 0.2

    calculate_discount(price, discount)

    greet_user("Developer")
    greet_user(42)


if __name__ == "__main__":
    main()
