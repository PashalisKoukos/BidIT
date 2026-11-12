import json
import random
import socket
import threading
import time
from pathlib import Path
from decimal import Decimal, InvalidOperation


# Network configuration.
HOST = "127.0.0.1"
PORT = 5000

# Each auction receives its own random duration.
# These short limits are useful for testing the application.
MIN_AUCTION_DURATION_SECONDS = 60
MAX_AUCTION_DURATION_SECONDS = 180

# Load auction item definitions from a JSON file located next to this script.
# This keeps product data separate from the server implementation.
ITEMS_FILE = Path(__file__).with_name("items.json")


def load_items():
    """Load and validate auction items from the external JSON file."""
    try:
        with ITEMS_FILE.open("r", encoding="utf-8") as json_file:
            data = json.load(json_file)
    except FileNotFoundError as error:
        raise RuntimeError(
            f"Required data file was not found: {ITEMS_FILE}"
        ) from error
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"The JSON file contains invalid JSON: {error}"
        ) from error

    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ValueError("items.json must contain an 'items' array.")

    loaded_items = []
    used_ids = set()

    for entry in data["items"]:
        if not isinstance(entry, dict):
            raise ValueError("Every item in items.json must be a JSON object.")

        try:
            item_id = int(entry["item_id"])
            name = str(entry["name"]).strip()
            starting_price = Decimal(str(entry["starting_price"]))
        except (KeyError, TypeError, ValueError, InvalidOperation) as error:
            raise ValueError(
                "Each item needs item_id, name and starting_price fields."
            ) from error

        if item_id <= 0 or item_id in used_ids:
            raise ValueError("Item IDs must be positive and unique.")
        if not name:
            raise ValueError(f"Item {item_id} must have a non-empty name.")
        if (
            not starting_price.is_finite()
            or starting_price <= 0
            or starting_price != starting_price.quantize(Decimal("0.01"))
        ):
            raise ValueError(
                f"Item {item_id} must have a positive price with at most two decimals."
            )

        used_ids.add(item_id)
        loaded_items.append(
            {
                "item_id": item_id,
                "name": name,
                "current_price": starting_price,
                "highest_bidder": None,
                "status": "ACTIVE",
            }
        )

    if not loaded_items:
        raise ValueError("The items array in items.json cannot be empty.")

    return loaded_items


# Load the products once when the server starts.
items = load_items()

# Assign an independent random deadline to every auction.
# monotonic() is used because it is suitable for measuring elapsed time.
server_start_time = time.monotonic()

for item in items:
    duration = random.randint(
        MIN_AUCTION_DURATION_SECONDS,
        MAX_AUCTION_DURATION_SECONDS,
    )
    item["auction_end_time"] = server_start_time + duration
    print(
        f"Auction {item['item_id']} ({item['name']}) will expire in "
        f"{duration} seconds."
    )

# Store connected sockets and their usernames.
clients = {}

# Protect shared auction state and client registration.
state_lock = threading.Lock()

# Prevent concurrent writes from mixing messages on the same socket.
send_locks = {}


def find_item(item_id):
    """Find an auction item by its unique ID."""
    for item in items:
        if item["item_id"] == item_id:
            return item
    return None


def format_price(price):
    """Return a price with exactly two decimal places."""
    return f"{price:.2f}"


def send_message(client_socket, message):
    """Send one newline-terminated COT/1 message to a connected client."""
    # Read the socket-specific lock without holding it during network I/O.
    with state_lock:
        socket_lock = send_locks.get(client_socket)

    if socket_lock is None:
        return False

    try:
        # Serialize writes so messages cannot overlap on the same connection.
        with socket_lock:
            client_socket.sendall((message + "\n").encode("utf-8"))
        return True
    except OSError:
        # The client may have disconnected unexpectedly.
        return False


def broadcast(message):
    """Send a server event to every currently connected client."""
    # Take a snapshot so the clients dictionary is not held during network I/O.
    with state_lock:
        connected_sockets = list(clients.keys())

    for client_socket in connected_sockets:
        if not send_message(client_socket, message):
            print("Could not send an event to one client.")


def auction_timer():
    """Expire each auction independently when its own deadline is reached."""
    while True:
        # Check deadlines periodically; expiration may be delayed by up to
        # approximately one second because of this sleep.
        time.sleep(1)
        expired_items = []

        # Update statuses and collect results atomically.
        with state_lock:
            current_time = time.monotonic()

            for item in items:
                if (
                    item["status"] == "ACTIVE"
                    and current_time >= item["auction_end_time"]
                ):
                    # Mark each auction as expired exactly once.
                    item["status"] = "EXPIRED"
                    expired_items.append(
                        {
                            "item_id": item["item_id"],
                            "winner": item["highest_bidder"],
                            "price": item["current_price"],
                        }
                    )

        # Announce winners after releasing the shared-state lock.
        for expired in expired_items:
            winner = expired["winner"]
            final_price = format_price(expired["price"])

            if winner is None:
                winner_name = "-"
                print(
                    f"Auction {expired['item_id']} expired without bids."
                )
            else:
                winner_name = winner
                print(
                    f"Auction {expired['item_id']} winner: {winner_name}, "
                    f"final price: {final_price}"
                )

            event = (
                f"BROADCAST WINNER {expired['item_id']} "
                f"{winner_name} {final_price}"
            )
            broadcast(event)

        # Stop the timer once every auction has expired.
        with state_lock:
            all_expired = all(
                item["status"] == "EXPIRED"
                for item in items
            )

        if all_expired:
            print("All auctions have expired.")
            break


def handle_client(client_socket, client_address):
    """Handle one client connection in its own thread."""
    username = None
    print(f"Client connected from {client_address}")

    try:
        # Read complete newline-terminated protocol messages.
        with client_socket.makefile(
            "r",
            encoding="utf-8",
            newline="\n",
        ) as reader:
            for line in reader:
                message = line.rstrip("\r\n")
                parts = message.split()

                print(f"Received from {client_address}: {message}")

                if not parts:
                    send_message(client_socket, "400 INVALID_REQUEST")
                    continue

                # Process the initial HELLO command.
                if parts[0] == "HELLO":
                    if len(parts) != 2:
                        send_message(client_socket, "400 INVALID_REQUEST")
                        continue

                    requested_username = parts[1]

                    # Usernames must be unique among currently connected clients.
                    with state_lock:
                        if username is not None:
                            # A client cannot change its username mid-session.
                            response = "400 INVALID_REQUEST"
                        elif any(
                            name.lower() == requested_username.lower()
                            for name in clients.values()
                        ):
                            response = "409 USERNAME_TAKEN"
                        else:
                            clients[client_socket] = requested_username
                            send_locks[client_socket] = threading.Lock()
                            username = requested_username
                            response = f"200 WELCOME {username}"

                    send_message(client_socket, response)
                    continue

                # Require HELLO before processing any other command.
                if username is None:
                    send_message(client_socket, "400 HELLO_REQUIRED")
                    continue

                # Return a snapshot of the current auction state.
                if parts[0] == "GET_ITEMS":
                    if len(parts) != 1:
                        send_message(client_socket, "400 INVALID_REQUEST")
                        continue

                    with state_lock:
                        items_for_json = [
                            {
                                "item_id": item["item_id"],
                                "name": item["name"],
                                "current_price": format_price(
                                    item["current_price"]
                                ),
                                "highest_bidder": item["highest_bidder"],
                                "status": item["status"],
                            }
                            for item in items
                        ]

                    # Internal deadlines are intentionally not exposed to clients.
                    data = json.dumps(
                        {"items": items_for_json},
                        ensure_ascii=False,
                    )
                    send_message(
                        client_socket,
                        f"200 ITEMS_LIST {data}",
                    )
                    continue

                # Process a bid request.
                if parts[0] == "BID":
                    if len(parts) != 3:
                        send_message(client_socket, "400 INVALID_REQUEST")
                        continue

                    try:
                        item_id = int(parts[1])
                        amount = Decimal(parts[2])

                        # Accept only finite, positive prices with two decimals
                        # at most, matching the COT/1 price format.
                        if (
                            not amount.is_finite()
                            or amount <= 0
                            or amount != amount.quantize(Decimal("0.01"))
                        ):
                            raise InvalidOperation

                    except (ValueError, InvalidOperation):
                        send_message(client_socket, "400 INVALID_REQUEST")
                        continue

                    # Check the item's own deadline and update its bid atomically.
                    with state_lock:
                        item = find_item(item_id)
                        current_time = time.monotonic()

                        if item is None:
                            result = f"404 ITEM_NOT_FOUND {item_id}"
                            accepted_bid = False

                        elif (
                            item["status"] != "ACTIVE"
                            or current_time >= item["auction_end_time"]
                        ):
                            result = f"403 AUCTION_EXPIRED {item_id}"
                            accepted_bid = False

                        elif amount <= item["current_price"]:
                            result = (
                                f"400 BID_TOO_LOW "
                                f"{format_price(item['current_price'])}"
                            )
                            accepted_bid = False

                        else:
                            # Save the new highest bid and bidder.
                            item["current_price"] = amount
                            item["highest_bidder"] = username

                            result = (
                                f"200 BID_ACCEPTED {item_id} "
                                f"{format_price(amount)}"
                            )
                            accepted_bid = True

                    # Reply directly to the client that placed the bid.
                    send_message(client_socket, result)

                    if accepted_bid:
                        # Notify all connected clients about the new highest bid.
                        event = (
                            f"BROADCAST NEW_BID {item_id} "
                            f"{format_price(amount)} {username}"
                        )
                        broadcast(event)

                        print(
                            f"Accepted bid: {username}, item {item_id}, "
                            f"price {format_price(amount)}"
                        )

                    continue

                # Close the client's session.
                if parts[0] == "QUIT":
                    if len(parts) != 1:
                        send_message(client_socket, "400 INVALID_REQUEST")
                    else:
                        send_message(client_socket, "200 BYE")
                    break

                # Reject any command not defined by COT/1.
                send_message(client_socket, "400 INVALID_REQUEST")

    except (OSError, UnicodeError) as error:
        print(f"Connection error for {client_address}: {error}")

    finally:
        # Remove the disconnected client and release its username.
        with state_lock:
            clients.pop(client_socket, None)
            send_locks.pop(client_socket, None)

        try:
            client_socket.close()
        except OSError:
            pass

        print(f"Client disconnected: {client_address}")


def main():
    """Start the TCP server and its background auction timer."""
    # Create and configure the TCP listening socket.
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server_socket.bind((HOST, PORT))
        server_socket.listen()

        # Ρύθμιση timeout για να λειτουργεί το Ctrl+C απο το τερματικό.
        server_socket.settimeout(1.0)

        print(f"COT/1 server listening on {HOST}:{PORT}")
        print(
            "Auction durations are randomized between "
            f"{MIN_AUCTION_DURATION_SECONDS} and "
            f"{MAX_AUCTION_DURATION_SECONDS} seconds."
        )

        # Run the auction timer independently from client connections.
        timer_thread = threading.Thread(
            target=auction_timer,
            daemon=True,
        )
        timer_thread.start()

        # Accept multiple clients until the server is stopped.
        while True:
            try:
                client_socket, client_address = server_socket.accept()

                client_thread = threading.Thread(
                    target=handle_client,
                    args=(client_socket, client_address),
                    daemon=True,
                )
                client_thread.start()
            except socket.timeout :
                # Αυτό συμβαίνει κάθε 1 δευτερόλεπτο αν δεν συνδεθεί κανείς,
                # επιτρέποντας στην Python να ελέγξει αν πατήθηκε Ctrl+C!
                continue


    except KeyboardInterrupt:
        print("\nStopping the COT/1 server...")

    finally:
        server_socket.close()
        print("COT/1 server stopped.")


if __name__ == "__main__":
    main()
