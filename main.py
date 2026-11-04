"""
Main entry point to run all COT/1 components:
- TCP Auction Server
- Flask Web Application
- Interactive CLI Client
"""

import threading
import time
import app
import client
import server


def start_server():
    """Start the central TCP auction server."""
    server.main()


def start_flask_app():
    """Start the Flask web application interface."""
    # Disable reloader and debug mode to run smoothly in a background thread
    app.app.run(host="127.0.0.1", port=5001, debug=False, use_reloader=False)


if __name__ == "__main__":
    print("=== Starting Cash or Trash Auction System ===")

    # 1. Start the TCP Server in a background thread
    print("[SYSTEM] Launching TCP Server on 127.0.0.1:5000...")
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    # Give the TCP server a second to bind to the port
    time.sleep(1)

    # 2. Start the Flask Web Application in a background thread
    print("[SYSTEM] Launching Flask Web App on http://127.0.0.1:5001...")
    web_thread = threading.Thread(target=start_flask_app, daemon=True)
    web_thread.start()

    # Give the web server a moment to boot up
    time.sleep(1)

    print("\n[SYSTEM] All servers are running!")
    print("[SYSTEM] Access the Web UI at: http://127.0.0.1:5001")
    print("[SYSTEM] Launching Interactive CLI Client below...\n")

    # 3. Run the interactive CLI Client in the main thread
    try:
        client.main()
    except KeyboardInterrupt:
        print("\n[SYSTEM] Shutting down application...")