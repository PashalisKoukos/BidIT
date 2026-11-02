
import socket
import json
import threading

# The server's address and port.
HOST = "127.0.0.1"
PORT = 5000


def receive_messages(reader, stop_event):
    # Continuously listen for server responses and broadcast events.
    while not stop_event.is_set():
        try:
            # Read one complete newline-terminated message.
            line = reader.readline()

            # An empty result indicates that the server closed the connection.
            if not line:
                if not stop_event.is_set():
                    print("\nThe server closed the connection.")

                stop_event.set()
                break

            # Remove the newline at the end of the message.
            message = line.rstrip("\r\n")

            # Handle the list of auction items.
            if message.startswith("200 ITEMS_LIST "):
                # Extract the JSON data from the server response.
                json_data = message[len("200 ITEMS_LIST "):]

                # Convert the JSON text into a Python dictionary.
                auction_data = json.loads(json_data)

                print("\n--- Current auction items ---")

                # Display every auction item and its current state.
                for item in auction_data["items"]:
                    print(
                        f'ID: {item["item_id"]} | '
                        f'Name: {item["name"]} | '
                        f'Price: {item["current_price"]} | '
                        f'Highest bidder: {item["highest_bidder"]} | '
                        f'Status: {item["status"]}'
                    )

                print("-----------------------------")

            # Handle live notifications about accepted bids.
            elif message.startswith("BROADCAST NEW_BID "):
                # Split the message into its protocol components.
                parts = message.split(maxsplit=4)

                if len(parts) == 5:
                    # The message format is:
                    # BROADCAST NEW_BID <item_id> <price> <username>
                    _, _, event_type, item_id, details = parts

                    print(
                        f"\n[LIVE UPDATE] Item {item_id}: "
                        f"{details}"
                    )
                else:
                    # Display the original message if its format is unexpected.
                    print("\n[SERVER EVENT]", message)

            # Handle notifications that an auction has ended.
            elif message.startswith("BROADCAST WINNER "):
                # Split the winner announcement into its components.
                parts = message.split()

                if len(parts) == 5:
                    # The message format is:
                    # BROADCAST WINNER <item_id> <winner> <final_price>
                    item_id = parts[2]
                    winner = parts[3]
                    final_price = parts[4]

                    # A dash means that nobody placed a bid.
                    if winner == "-":
                        print(
                            f"\n[AUCTION ENDED] Item {item_id}: "
                            "No bids were placed."
                        )
                    else:
                        # Display the winner and the final auction price.
                        print(
                            f"\n[AUCTION ENDED] Item {item_id}: "
                            f"Winner: {winner}, "
                            f"final price: {final_price}"
                        )
                else:
                    # Handle an incorrectly formatted winner announcement.
                    print("\n[SERVER EVENT]", message)

            else:
                # Display welcome messages, bid responses, and errors.
                print("\n[SERVER]", message)

        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError
        ) as error:
            # Report receiving or JSON parsing errors.
            if not stop_event.is_set():
                print(f"\nError receiving server message: {error}")

            stop_event.set()
            break


# Ask the user to choose a username before connecting.
username = input("Choose a username: ").strip()

# Usernames must be non-empty and contain no whitespace.
if not username or any(character.isspace() for character in username):
    print("Username must be non-empty and contain no spaces.")
    raise SystemExit(1)

# Create a TCP socket using IPv4.
client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

try:
    # Connect to the COT/1 server.
    client_socket.connect((HOST, PORT))

except OSError as error:
    # Display a helpful message if the server is unavailable.
    print(f"Could not connect to the server: {error}")
    client_socket.close()
    raise SystemExit(1)

# Create a text reader for complete server messages.
reader = client_socket.makefile(
    "r",
    encoding="utf-8",
    newline="\n"
)

# This event signals that the client should stop receiving messages.
stop_event = threading.Event()

# Start a background thread to receive server responses and events.
receiver_thread = threading.Thread(
    target=receive_messages,
    args=(reader, stop_event),
    daemon=True
)
receiver_thread.start()

try:
    # Introduce the client to the server.
    # The server will accept or reject the requested username.
    client_socket.sendall(
        f"HELLO {username}\n".encode("utf-8")
    )

    # Display the commands supported by this client.
    print("\nCommands:")
    print("  ITEMS                 - Show all auction items")
    print("  BID <id> <amount>     - Submit a bid")
    print("  QUIT                  - Disconnect")

    # Read and send user commands until the client exits.
    while not stop_event.is_set():
        try:
            command = input("\nCOT/1> ").strip()

        except EOFError:
            # Exit if the input stream is closed.
            break

        if not command:
            continue

        # Convert the user-friendly ITEMS command into COT/1 syntax.
        if command.upper() == "ITEMS":
            command = "GET_ITEMS"

        # Send the command to the server.
        try:
            client_socket.sendall(
                (command + "\n").encode("utf-8")
            )

        except OSError:
            print("Could not send the command. The connection may be closed.")
            break

        # Exit the input loop after sending QUIT.
        if command.upper() == "QUIT":
            break

finally:
    # Signal the receiving thread to stop.
    stop_event.set()

    # Close the socket to interrupt any pending network read.
    try:
        client_socket.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass

    # Close the text reader.
    try:
        reader.close()
    except OSError:
        pass

    # Close the TCP connection.
    client_socket.close()

    print("Disconnected from the COT/1 server.")
