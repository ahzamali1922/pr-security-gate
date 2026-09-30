const unusedVariable = 10;

function calculateTotal(price, tax) {
    if (price > 0) {
        return price + tax;
    }
}

console.log(calculateTotal(100, 18));