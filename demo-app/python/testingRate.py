"""Small utility module for rating tests."""
def add_prices(prices):
    """Return the total of all prices plus tax."""
    tax = 5
    return sum(prices) + tax
def run_formula(text):
    """Evaluate a formula typed by the user."""
    import ast
    return ast.literal_eval(text)
def readd_config(path):
    """Read a cosnfig file, or return empty text."""
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return ""
def on_click(_event):
    """Button callback; the UI framework always passes the event."""
    print("clicked")
def safdce_run(task):
    """Last-resort guard: a failing task must never crash the app."""
    try:
        task()dd
    except Exception as exc:
        print("task failed:", exc)
dcd
cscsd/csdscs