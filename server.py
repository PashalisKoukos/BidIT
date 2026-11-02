
import socket
import json
import threading
import time
from decimal import Decimal, InvalidOperation

# Network configuration.
HOST = "127.0.0.1"
PORT = 5000

# Auction duration in seconds.
# Use 60 seconds for testing.
# Change this to 20 * 60 for the final demonstration.
AUCTION_DURATION_SECONDS = 60

# All auctions start when the server starts.
server_start_time = time.monotonic()
auction_end_time = server_start_time + AUCTION_DURATION_SECONDS

# Define the five auction items.
items = [
    {"item_id": 1, "name": "Vintage Lamp", "current_price": Decimal("25.00"), "highest_bidder": None, "status": "ACTIVE"},
    {"item_id": 2, "name": "Old Camera", "current_price": Decimal("40.00"), "highest_bidder": None, "status": "ACTIVE"},
    {"item_id": 3, "name": "Antique Clock", "current_price": Decimal("60.00"), "highest_bidder": None, "status": "ACTIVE"},
    {"item_id": 4, "name": "Vintage Radio", "current_price": Decimal("35.00"), "highest_bidder": None, "status": "ACTIVE"},
    {"item_id": 5, "name": "Collectible Vase", "current_price": Decimal("50.00"), "highest_bidder": None, "status": "ACTIVE"}
]

# Store connected sockets and their usernames.
clients = {}

# Protect shared auction state and client registration.
state_lock = threading.Lock()

# Prevent concurrent writes from mixing messages on the same socket.
send_locks = {}


def find_item(item_id):
    # Find an item by its unique ID.
    for item in items:
        if item["item_id"] == item_id:
            return item
    return None


def format_price(price):
    # Return a price with exactly two decimal places.
    return f"{price:.2f}"


def send_message(client_socket, message):
    # Get the socket-specific lock without holding it during network I/O.
    with state_lock:
        socket_lock = send_locks.get(client_socket)

    if socket_lock is None:
        return False

    try:
        # Send one complete newline-terminated protocol message.
        with socket_lock:
            client_socket.sendall((message + "\n").encode("utf-8"))
        return True
    except OSError:
        # The client may have disconnected unexpectedly.
        return False


def broadcast(message):
    # Take a snapshot of the connected sockets.
    with state_lock:
        connected_sockets = list(clients.keys())

    # Send the event individually to every connected client.
    for client_socket in connected_sockets:
        if not send_message(client_socket, message):
            print("Could not send an event to one client.")


def auction_timer():
    # Check whether any auctions have reached their deadline.
    while True:
        time.sleep(1)

        expired_items = []

        # Update auction statuses atomically.
        with state_lock:
            current_time = time.monotonic()

            for item in items:
                if (
                    item["status"] == "ACTIVE"
                    and current_time >= auction_end_time
                ):
                    # Mark the auction as expired exactly once.
                    item["status"] = "EXPIRED"
                    expired_items.append({
                        "item_id": item["item_id"],
                        "winner": item["highest_bidder"],
                        "price": item["current_price"]
                    })

        # Broadcast winner announcements after releasing the state lock.
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
                    f"Auction {expired['item_id']} winner: "
                    f"{winner_name}, final price: {final_price}"
                )

            event = (
                f"BROADCAST WINNER {expired['item_id']} "
                f"{winner_name} {final_price}"
            )
            broadcast(event)

        # Stop checking once every auction has expired.
        with state_lock:
            all_expired = all(
                item["status"] == "EXPIRED"
                for item in items
            )

        if all_expired:
            print("All auctions have expired.")
            break


def handle_client(client_socket, client_address):
    # Handle one client connection in its own thread.
    username = None

    print(f"Client connected from {client_address}")

    try:
        # Read complete newline-terminated protocol messages.
        with client_socket.makefile(
            "r", encoding="utf-8", newline="\n"
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

                    # Usernames must be unique among connected clients.
                    with state_lock:
                        if username is not None:
                            # A client cannot change its username mid-session.
                            accepted = False
                            response = "400 INVALID_REQUEST"
                        elif any(
                            name.lower() == requested_username.lower()
                            for name in clients.values()
                        ):
                            accepted = False
                            response = "409 USERNAME_TAKEN"
                        else:
                            clients[client_socket] = requested_username
                            send_locks[client_socket] = threading.Lock()
                            username = requested_username
                            accepted = True
                            response = f"200 WELCOME {username}"

                    send_message(client_socket, response)
                    continue

                # Require HELLO before all other commands.
                if username is None:
                    send_message(client_socket, "400 HELLO_REQUIRED")
                    continue

                # Return the current auction state.
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
                                "status": item["status"]
                            }
                            for item in items
                        ]

                    data = json.dumps(
                        {"items": items_for_json},
                        ensure_ascii=False
                    )
                    send_message(
                        client_socket,
                        f"200 ITEMS_LIST {data}"
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

                        # Validate the amount and its precision.
                        if (
                            not amount.is_finite()
                            or amount <= 0
                            or amount != amount.quantize(Decimal("0.01"))
                        ):
                            raise InvalidOperation

                    except (ValueError, InvalidOperation):
                        send_message(client_socket, "400 INVALID_REQUEST")
                        continue

                    # Check the deadline and update the bid atomically.
                    with state_lock:
                        item = find_item(item_id)
                        current_time = time.monotonic()

                        if item is None:
                            result = f"404 ITEM_NOT_FOUND {item_id}"
                            accepted_bid = False

                        elif (
                            item["status"] != "ACTIVE"
                            or current_time >= auction_end_time
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

                    # Reply directly to the client who placed the bid.
                    send_message(client_socket, result)

                    if accepted_bid:
                        # Notify every connected client about the new bid.
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


# Create and configure the TCP listening socket.
server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server_socket.bind((HOST, PORT))
server_socket.listen()

print(f"COT/1 server listening on {HOST}:{PORT}")
print(
    f"All auctions will expire in "
    f"{AUCTION_DURATION_SECONDS} seconds."
)

# Start the auction timer in a background thread.
timer_thread = threading.Thread(
    target=auction_timer,
    daemon=True
)
timer_thread.start()

try:
    # Accept multiple clients until the server is stopped.
    while True:
        client_socket, client_address = server_socket.accept()

        client_thread = threading.Thread(
            target=handle_client,
            args=(client_socket, client_address),
            daemon=True
        )
        client_thread.start()

except KeyboardInterrupt:
    print("\nStopping the COT/1 server...")

finally:
    server_socket.close()
    print("COT/1 server stopped.")
