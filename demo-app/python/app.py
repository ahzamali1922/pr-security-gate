
def calculate_discount(price, discount):
    result = price - (price * discount)
    return result
dfsfv

def read_fsddsile(filename):
    try:
        file = open(filename, "r")
        data = file.read()
        return data
    except OSError:
        return None

def greeddt_user(name):
    message = "Hello " + name
    print(message)


def main():
    price = 100
    discount = 0.2

    calculate_discount(price, discount)

    greet_user("Developer")


if __name__ == "__main__":
    main()

def vedansh(): pass