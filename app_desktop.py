"""
Desktop launcher — starts Flask and opens it in Chrome/Edge app mode.
App mode = no URL bar, no tabs, looks and feels like a native desktop app.
"""

import os
import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vendor_pricing.web import create_app


def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def find_browser():
    """Return path to Chrome or Edge — whichever is installed."""
    candidates = [
        # Google Chrome
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        # Microsoft Edge (always present on Windows 10/11)
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def start_flask(app, port):
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)


def main():
    port = find_free_port()
    flask_app = create_app()

    # Start Flask in a background thread
    t = threading.Thread(target=start_flask, args=(flask_app, port), daemon=True)
    t.start()
    time.sleep(1.5)  # give Flask a moment to start

    url = f"http://127.0.0.1:{port}"
    browser = find_browser()

    if browser:
        # App mode: looks like a real desktop window
        proc = subprocess.Popen([
            browser,
            f"--app={url}",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={os.path.expandvars(r'%TEMP%\VendorPricingApp')}",
        ])
        # Keep the server alive until the browser window closes
        proc.wait()
    else:
        # Fallback: open in default browser
        webbrowser.open(url)
        # Keep server alive indefinitely (Ctrl+C or close terminal to stop)
        signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
        while True:
            time.sleep(1)


if __name__ == "__main__":
    main()
