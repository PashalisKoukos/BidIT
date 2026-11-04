# Cash or Trash / BidIT - Live Auction System (COT/1 Protocol)

![Python](https://img.shields.io/badge/Python-3.8%2B-blue?style=for-the-badge&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-2.x-black?style=for-the-badge&logo=flask&logoColor=white)
![JavaScript](https://img.shields.io/badge/JavaScript-ES6%2B-F7DF1E?style=for-the-badge&logo=javascript&logoColor=black)
![HTML5](https://img.shields.io/badge/HTML5-E34F26?style=for-the-badge&logo=html5&logoColor=white)
![CSS3](https://img.shields.io/badge/CSS3-1572B6?style=for-the-badge&logo=css3&logoColor=white)
![JSON](https://img.shields.io/badge/JSON-000000?style=for-the-badge&logo=json&logoColor=white)

Real-time auction platform based on a Client-Server architecture using the custom **COT/1 (Cash or Trash Protocol v1)** application protocol over **TCP Sockets**.

The system features a multi-threaded TCP Server, a CLI Client for terminal interaction, and a Web Application (Flask + JS Polling).

## System Architecture

1. **COT/1 TCP Server (`server.py`)**:
   - Single Source of Truth for prices, highest bidders, and auction statuses.
   - Manages concurrent client sessions via multithreading and strict state locking (`threading.Lock`).
   - Tracks individual auction expiration times dynamically.

2. **CLI Client (`client.py`)**:
   - Console client communicating directly with the TCP Server over raw sockets.
   - Listens for real-time broadcast events (new bids and auction winners).

3. **Web Application (`app.py`, `index.html`, `app.js`, `style.css`)**:
   - Web interface built with Flask.
   - Translates HTTP requests to transient COT/1 TCP socket commands.
   - Frontend polls `/api/items` every 3 seconds to reflect live price changes without page reloads.

## Technical Specifications

- **Backend:** Python 3.8+
- **Networking:** Low-level TCP Sockets (`socket`), Threading (`threading`)
- **Web Layer:** Flask
- **Frontend:** HTML5, CSS3, JavaScript (Fetch API)
- **Data Format:** JSON

## COT/1 Protocol Specification

The protocol uses plain-text, newline-delimited (`\n`) messaging:

| Client Command | Server Response / Broadcast | Description |
|---|---|---|
| `HELLO <username>` | `200 WELCOME <username>` / `409 USERNAME_TAKEN` | Registers a unique session username. |
| `GET_ITEMS` | `200 ITEMS_LIST <json_array>` | Fetches current state of all items in JSON format. |
| `BID <item_id> <amount>` | `200 BID_ACCEPTED <id> <amount>` / `400 BID_TOO_LOW` | Submits a new bid for an active item. |
| `QUIT` | `200 BYE` | Closes the connection session. |
| N/A | `BROADCAST NEW_BID <id> <price> <user>` | Server event pushed when a new high bid is accepted. |
| N/A | `BROADCAST WINNER <id> <winner> <price>` | Server event pushed when an auction expires. |

## Installation and Setup

### 1. Prerequisites

Ensure Python 3.8+ is installed along with Flask:

```bash
pip install flask
```

### 2. Run the TCP Server

The TCP server manages item state from `items.json` and must be started first:

```bash
python server.py
```

*Listens on `127.0.0.1:5000` by default.*

### 3. Run the Web Interface (Optional)

Start the Flask web backend:

```bash
python app.py
```

Access the UI at `http://127.0.0.1:5001`.

### 4. Run the CLI Client (Optional)

Connect to the server directly from the terminal:

```bash
python client.py
```

## Repository Structure

```text
.
├── server.py        # Central TCP Server (COT/1 Protocol)
├── client.py        # Terminal CLI Client
├── app.py           # Flask Web Application Bridge
├── items.json       # Initial item definitions and prices
├── static/
│   ├── style.css    # Responsive stylesheet
│   └── app.js       # Live UI update & polling logic
└── templates/
    └── index.html   # Main web interface template
```

## Key Features

- **Thread-Safe State Management:** Synchronization locks prevent race conditions during concurrent bidding.
- **Monetary Precision:** Uses Python's `Decimal` module to avoid floating-point inaccuracies.
- **Dynamic Polling:** Frontend stays up to date using background HTTP polling.
- **Independent Expiration:** Each auction item features randomized independent deadlines.