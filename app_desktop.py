"""
Desktop launcher for the Vendor Pricing Tracker.
Starts the Flask server in a background thread, then opens it
in a native pywebview window (no browser, no URL bar).
"""

import sys
import os
import threading
import time
import socket

# Ensure vendor_pricing package is findable regardless of where this is run from
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import webview
from vendor_pricing.web import create_app


def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def start_flask(app, port):
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)


def main():
    port = find_free_port()
    flask_app = create_app()

    # Start Flask in a daemon thread (dies when window closes)
    t = threading.Thread(target=start_flask, args=(flask_app, port), daemon=True)
    t.start()

    # Give Flask a moment to start
    time.sleep(1.2)

    # Open the native desktop window
    window = webview.create_window(
        title="Vendor Pricing Tracker — Creative Affairs Catering",
        url=f"http://127.0.0.1:{port}",
        width=1280,
        height=820,
        min_size=(900, 600),
        resizable=True,
    )

    webview.start(debug=False)


if __name__ == "__main__":
    main()
