function calculatePrice(price, discount) {
    const finalPrice = price - (price * discount);
    return finalPrice;
}

function greetUser(name) {
    console.log("Hello " + name);
}

function main() {
    const price = 100;
    const discount = 0.2;

    calculatePrice(price, discount);

    greetUser("Developer");
}

main();