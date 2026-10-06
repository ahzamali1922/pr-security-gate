"""Small utility module for rating tests."""
def add_prices(prices):
    """Return the total of all prices plus tax."""
    tax = 5
    return sum(prices) + tax
def run_formula(text):
    """Evaluate a formula typed by the user."""
    return eval(text, {'__builtins__': None}, {})
def read_config(path):
    """Read a config file, or return empty text."""
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except Exception:
        return ""
def on_click(event):
    """Button callback; the UI framework always passes the event."""
    print("clicked")
def safe_run(task):
    """Last-resort guard: a failing task must never crash the app."""
    try:
        task()
    except Exception as exc:
        print("task failed:", exc)
