
"""
Cash or Trash Auction - Web Application

This Flask application provides the web interface for the auction system.
It communicates with the central COT/1 TCP server instead of maintaining
its own copy of the auction state.

The TCP server remains the single source of truth for bids and item status.
"""

import json
import socket
import uuid
from decimal import Decimal, InvalidOperation

from flask import Flask, jsonify, render_template, request


# ---------------------------------------------------------
# Flask and TCP configuration
# ---------------------------------------------------------

app = Flask(__name__)

# The web application connects to the central COT/1 server.
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 5000

# Prevent a web request from waiting forever for the TCP server.
SOCKET_TIMEOUT = 5

# Restrict usernames to a single word with a reasonable maximum length.
MAX_USERNAME_LENGTH = 30


# ---------------------------------------------------------
# TCP communication helpers
# ---------------------------------------------------------

def receive_message(connection_file):
    """
    Read one complete newline-delimited COT/1 message.

    The protocol uses one text message per line. Using makefile() allows
    Python to read until the newline that terminates the server response.
    """
    line = connection_file.readline()

    if not line:
        raise ConnectionError("The COT/1 server closed the connection.")

    return line.decode("utf-8").strip()


def send_cot_command(username, command):
    """
    Open a TCP connection, complete the HELLO handshake, and send a command.

    Each web request uses a temporary TCP connection. This keeps the Flask
    layer simple and leaves auction state management to the TCP server.
    """
    with socket.create_connection(
        (SERVER_HOST, SERVER_PORT),
        timeout=SOCKET_TIMEOUT
    ) as connection:

        # Apply a timeout to socket operations after connecting.
        connection.settimeout(SOCKET_TIMEOUT)

        # A file wrapper makes newline-delimited messages easy to read.
        with connection.makefile("rb") as connection_file:

            # Register this connection with the COT/1 server.
            hello_message = f"HELLO {username}\n"
            connection.sendall(hello_message.encode("utf-8"))

            welcome_response = receive_message(connection_file)

            # Stop if the server rejects the username or handshake.
            if not welcome_response.startswith("200 WELCOME "):
                return welcome_response

            # Send the requested COT/1 command.
            request_message = f"{command}\n"
            connection.sendall(request_message.encode("utf-8"))

            # Read the direct response to the command.
            return receive_message(connection_file)


def get_items_from_server():
    """
    Request the current item list from the COT/1 server.

    A unique temporary username avoids collisions with normal web users
    and with other web requests running at the same time.
    """
    temporary_username = "Web" + uuid.uuid4().hex[:12]

    response = send_cot_command(
        temporary_username,
        "GET_ITEMS"
    )

    # The item list is the only response whose payload contains JSON.
    prefix = "200 ITEMS_LIST "

    if not response.startswith(prefix):
        raise RuntimeError(f"Could not retrieve auction items: {response}")

    json_payload = response[len(prefix):]
    items_data = json.loads(json_payload)

    return items_data["items"]


# ---------------------------------------------------------
# User input validation
# ---------------------------------------------------------

def validate_username(raw_username):
    """
    Validate the username received from the web form.

    COT/1 represents usernames as a single token, so whitespace is not
    permitted. The server performs its own uniqueness check as well.
    """
    username = (raw_username or "").strip()

    if not username:
        return None, "Please enter a username."

    if len(username) > MAX_USERNAME_LENGTH:
        return None, f"Your username must be {MAX_USERNAME_LENGTH} characters or fewer."

    if any(character.isspace() for character in username):
        return None, "Your username cannot contain spaces."

    # Keep the username compatible with the plain-text COT/1 command format.
    if any(character in username for character in "<>\r\n"):
        return None, "Your username contains an unsupported character."

    return username, None


def validate_bid_amount(raw_amount):
    """
    Parse and validate a bid using Decimal rather than binary floating point.

    Auction prices are monetary values, so Decimal avoids common floating
    point rounding problems. The protocol sends prices with two decimals.
    """
    try:
        amount = Decimal(raw_amount)
    except (InvalidOperation, TypeError, ValueError):
        return None, "Enter a valid bid amount."

    if not amount.is_finite() or amount <= 0:
        return None, "The bid must be a positive amount."

    # Reject values that have more than two decimal places.
    if amount.as_tuple().exponent < -2:
        return None, "Use no more than two decimal places."

    return amount, None


# ---------------------------------------------------------
# Human-readable notifications
# ---------------------------------------------------------

def format_bid_response(response):
    """
    Convert a COT/1 server response into a friendly web notification.

    The original response is still generated by the TCP server. This
    function only changes how that response is presented to the user.
    """
    parts = response.split()

    if response.startswith("200 BID_ACCEPTED "):
        # Expected format: 200 BID_ACCEPTED <item_id> <new_price>
        price = parts[3] if len(parts) >= 4 else "updated"
        return (
            "success",
            f"Your bid was accepted! The new price is €{price}."
        )

    if response.startswith("400 BID_TOO_LOW "):
        # Expected format: 400 BID_TOO_LOW <current_price>
        price = parts[2] if len(parts) >= 3 else "unavailable"
        return (
            "warning",
            f"Your bid was too low. The current price is €{price}."
        )

    if response.startswith("403 AUCTION_EXPIRED "):
        return (
            "warning",
            "This auction has ended. You can no longer place a bid."
        )

    if response.startswith("404 ITEM_NOT_FOUND "):
        return (
            "error",
            "The selected item could not be found."
        )

    if response.startswith("409 USERNAME_TAKEN"):
        return (
            "error",
            "That username is already in use. Please try another one."
        )

    if response.startswith("400 INVALID_REQUEST"):
        return (
            "error",
            "The server could not understand the bid request."
        )

    if response.startswith("400 HELLO_REQUIRED"):
        return (
            "error",
            "The connection could not be registered with the server."
        )

    # Keep unexpected server replies understandable without exposing
    # implementation details as the main user-facing message.
    return (
        "error",
        "The bid could not be processed. Please check the details and try again."
    )


# ---------------------------------------------------------
# Web routes
# ---------------------------------------------------------

@app.route("/")
def index():
    """
    Render the main auction page with the latest server-side item list.
    """
    try:
        items = get_items_from_server()

        return render_template(
            "index.html",
            items=items,
            notification=None,
            error=None
        )

    except (OSError, ConnectionError, RuntimeError, ValueError, KeyError) as exc:
        app.logger.warning("Could not load auction items: %s", exc)

        return render_template(
            "index.html",
            items=[],
            notification=None,
            error="The auction server is unavailable. Please try again shortly."
        ), 503


@app.route("/api/items")
def api_items():
    """
    Return the latest item data as JSON for the browser's polling script.

    The frontend periodically calls this endpoint to refresh prices and
    auction statuses without reloading the entire page.
    """
    try:
        items = get_items_from_server()
        response = jsonify({"items": items})
        response.headers["Cache-Control"] = "no-store"
        return response

    except (OSError, ConnectionError, RuntimeError, ValueError, KeyError) as exc:
        app.logger.warning("Could not refresh auction items: %s", exc)

        return jsonify({
            "error": "The auction server is temporarily unavailable."
        }), 503


@app.route("/bid", methods=["POST"])
def place_bid():
    """
    Validate a submitted bid, forward it to the COT/1 server, and render
    the auction page with a user-friendly notification.
    """
    username, username_error = validate_username(
        request.form.get("username")
    )

    if username_error:
        return render_template(
            "index.html",
            items=get_items_from_server(),
            notification={
                "type": "error",
                "message": username_error
            },
            error=None
        ), 400

    raw_item_id = (request.form.get("item_id") or "").strip()

    try:
        item_id = int(raw_item_id)
    except (TypeError, ValueError):
        return render_template(
            "index.html",
            items=get_items_from_server(),
            notification={
                "type": "error",
                "message": "The selected item ID is invalid."
            },
            error=None
        ), 400

    amount, amount_error = validate_bid_amount(
        request.form.get("amount")
    )

    if amount_error:
        return render_template(
            "index.html",
            items=get_items_from_server(),
            notification={
                "type": "error",
                "message": amount_error
            },
            error=None
        ), 400

    # Format the amount according to the COT/1 price representation.
    formatted_amount = format(amount, ".2f")
    command = f"BID {item_id} {formatted_amount}"

    try:
        # The central TCP server decides whether the bid is accepted.
        server_response = send_cot_command(username, command)

        notification_type, notification_message = format_bid_response(
            server_response
        )

        # Refresh the list after the bid so the page shows the latest price.
        items = get_items_from_server()

        return render_template(
            "index.html",
            items=items,
            notification={
                "type": notification_type,
                "message": notification_message
            },
            error=None
        )

    except (OSError, ConnectionError, RuntimeError, ValueError, KeyError) as exc:
        app.logger.warning("Could not submit bid: %s", exc)

        # Try to show the current auction list even if the bid request failed.
        try:
            items = get_items_from_server()
        except (OSError, ConnectionError, RuntimeError, ValueError, KeyError):
            items = []

        return render_template(
            "index.html",
            items=items,
            notification=None,
            error="The Auction Server is currently Offline. Please Try Again Later."
        ), 503


# ---------------------------------------------------------
# Application entry point
# ---------------------------------------------------------

if __name__ == "__main__":
    # Debug mode is disabled to avoid exposing the interactive debugger.
    # The application is bound to localhost for this project setup.
    app.run(
        host="127.0.0.1",
        port=5001,
        debug=False
    )
