
import json
import socket
import uuid
from decimal import Decimal, InvalidOperation

from flask import Flask, render_template, request


# Create the Flask application.
app = Flask(__name__)

# Define the address of the existing COT/1 TCP server.
COT_SERVER_HOST = "127.0.0.1"
COT_SERVER_PORT = 5000

# Prevent the web application from waiting indefinitely for the server.
SOCKET_TIMEOUT = 5


def receive_message(connection_file):
    # Read one complete newline-terminated COT/1 message.
    message = connection_file.readline()

    # Detect if the TCP server closed the connection unexpectedly.
    if not message:
        raise ConnectionError("The COT server closed the connection.")

    # Remove the line-ending characters from the message.
    return message.rstrip("\r\n")


def send_cot_command(username, command):
    # Open a new TCP connection for this web request.
    with socket.create_connection(
        (COT_SERVER_HOST, COT_SERVER_PORT),
        timeout=SOCKET_TIMEOUT
    ) as connection:

        # Set a timeout for subsequent socket operations.
        connection.settimeout(SOCKET_TIMEOUT)

        # Read protocol messages as UTF-8 text lines.
        with connection.makefile(
            "r",
            encoding="utf-8",
            newline="\n"
        ) as connection_file:

            # Register the username before sending any other command.
            hello_message = f"HELLO {username}\n"
            connection.sendall(hello_message.encode("utf-8"))

            # Read and verify the server's welcome response.
            welcome = receive_message(connection_file)

            if not welcome.startswith("200 WELCOME "):
                raise RuntimeError(welcome)

            # Send the requested COT/1 command.
            command_message = f"{command}\n"
            connection.sendall(command_message.encode("utf-8"))

            # Read the direct response to the command.
            return receive_message(connection_file)


def get_items_from_server():
    # Use a temporary unique username for this read-only request.
    temporary_username = "Web" + uuid.uuid4().hex[:12]

    # Request the current auction items from the TCP server.
    response = send_cot_command(
        temporary_username,
        "GET_ITEMS"
    )

    # Verify that the server returned the expected response.
    if not response.startswith("200 ITEMS_LIST "):
        raise RuntimeError(response)

    # Extract the JSON document following the protocol prefix.
    json_data = response[len("200 ITEMS_LIST "):]

    # Decode the JSON document and return its list of items.
    items_data = json.loads(json_data)
    return items_data["items"]


@app.route("/")
def home():
    # Load the latest auction information for the main page.
    try:
        items = get_items_from_server()

        # Display the auction items in the HTML template.
        return render_template(
            "index.html",
            items=items,
            message=request.args.get("message"),
            error=None
        )

    except (
        OSError,
        ConnectionError,
        RuntimeError,
        ValueError,
        KeyError,
        json.JSONDecodeError
    ) as error:
        # Display a useful error if the server cannot be reached.
        return (
            render_template(
                "index.html",
                items=[],
                message=None,
                error=str(error)
            ),
            503
        )


@app.route("/api/items")
def api_items():
    # Return the latest auction items as JSON for the browser.
    from flask import jsonify

    try:
        # Retrieve the current auction state from the COT/1 server.
        items = get_items_from_server()

        # Convert the Python item list into an HTTP JSON response.
        return jsonify({"items": items})

    except (
        OSError,
        ConnectionError,
        RuntimeError,
        ValueError,
        KeyError,
        json.JSONDecodeError
    ) as error:
        # Return a JSON error if the TCP server is unavailable.
        return jsonify({"error": str(error)}), 503

@app.route("/bid", methods=["POST"])
def place_bid():
    # Read the form fields submitted by the browser.
    username = request.form.get("username", "").strip()
    item_id_text = request.form.get("item_id", "").strip()
    amount_text = request.form.get("amount", "").strip()

    # Usernames must be a single word because COT/1 uses spaces
    # to separate command arguments.
    if (
        not username
        or len(username) > 30
        or any(character.isspace() for character in username)
    ):
        return render_template(
            "index.html",
            items=get_items_from_server(),
            message=None,
            error="Enter a username without spaces (maximum 30 characters)."
        ), 400

    # Validate the product ID and bid amount before sending them.
    try:
        item_id = int(item_id_text)
        amount = Decimal(amount_text)

        # Accept only positive prices with at most two decimal places.
        if (
            item_id <= 0
            or not amount.is_finite()
            or amount <= 0
            or amount != amount.quantize(Decimal("0.01"))
        ):
            raise ValueError("Invalid item ID or bid amount.")

    except (ValueError, InvalidOperation):
        return render_template(
            "index.html",
            items=get_items_from_server(),
            message=None,
            error="Enter a valid item ID and a positive amount with up to two decimal places."
        ), 400

    # Format the amount consistently with the COT/1 protocol.
    formatted_amount = f"{amount:.2f}"

    try:
        # Submit the bid to the authoritative TCP server.
        response = send_cot_command(
            username,
            f"BID {item_id} {formatted_amount}"
        )

        # Retrieve the latest prices after the bid attempt.
        items = get_items_from_server()

        # Show the server's response and refreshed auction data.
        return render_template(
            "index.html",
            items=items,
            message=response,
            error=None
        )

    except (
        OSError,
        ConnectionError,
        RuntimeError,
        ValueError,
        KeyError,
        json.JSONDecodeError
    ) as error:
        # Report communication errors without crashing the web app.
        try:
            items = get_items_from_server()
        except Exception:
            items = []

        return render_template(
            "index.html",
            items=items,
            message=None,
            error=str(error)
        ), 503


# Start the Flask development server when this file is executed directly.
if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5001,
        debug=True
    )
