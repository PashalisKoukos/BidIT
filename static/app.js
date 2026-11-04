
/* =========================================
   COT AUCTION - LIVE FRONTEND UPDATES
   ========================================= */

// Set the interval between requests for updated auction data.
const REFRESH_INTERVAL_MS = 3000;

// Remember whether a request is already running.
let refreshInProgress = false;

// Retrieve the auction grid from the HTML document.
const auctionGrid = document.querySelector(".auction-grid");

// Retrieve the main content area for displaying messages.
const mainContent = document.querySelector("main");


/* Create an HTML element safely using textContent for user data. */
function createTextElement(tagName, className, text) {
    // Create the requested HTML element.
    const element = document.createElement(tagName);

    // Apply a CSS class when one has been provided.
    if (className) {
        element.className = className;
    }

    // Insert the text as plain text, not as executable HTML.
    element.textContent = text ?? "";

    return element;
}


/* Update one product card using the latest server data. */
function updateAuctionCard(item) {
    // Find the existing card for this product using its item ID.
    const existingCard = auctionGrid.querySelector(
        `[data-item-id="${Number(item.item_id)}"]`
    );

    // Do not create an unknown card in this update function.
    if (!existingCard) {
        return;
    }

    // Update the current price displayed on the card.
    const priceElement = existingCard.querySelector(".price");

    if (priceElement) {
        // Convert the price to a number and display two decimal places.
        const currentPrice = Number(item.current_price);
        priceElement.textContent = Number.isFinite(currentPrice)
            ? `€${currentPrice.toFixed(2)}`
            : `€${item.current_price}`;
    }

    // Update the auction status.
    const statusElement = existingCard.querySelector(".auction-status");

    if (statusElement) {
        statusElement.textContent = `Status: ${item.status}`;

        // Apply different styles to active and expired auctions.
        statusElement.classList.toggle(
            "status-active",
            item.status === "ACTIVE"
        );

        statusElement.classList.toggle(
            "status-expired",
            item.status !== "ACTIVE"
        );
    }

    // Update the highest bidder information.
    const bidderElement = existingCard.querySelector(".highest-bidder");

    if (bidderElement) {
        bidderElement.textContent = item.highest_bidder
            ? `Highest bidder: ${item.highest_bidder}`
            : "No bids yet.";
    }

    // Show or hide the bidding form based on the auction status.
    const bidForm = existingCard.querySelector("form");
    const endedMessage = existingCard.querySelector(".ended-message");

    if (item.status === "ACTIVE") {
        // Keep the form available while the auction is active.
        if (bidForm) {
            bidForm.hidden = false;
        }

        // Hide the ended-auction message.
        if (endedMessage) {
            endedMessage.hidden = true;
        }
    } else {
        // Prevent further bids through the web interface.
        if (bidForm) {
            bidForm.hidden = true;
        }

        // Display a message when the auction has ended.
        if (endedMessage) {
            endedMessage.hidden = false;
        }
    }
}


/* Fetch the latest auction data from the Flask endpoint. */
async function refreshAuctionData() {
    // Avoid overlapping requests if one takes longer than expected.
    if (refreshInProgress) {
        return;
    }

    refreshInProgress = true;

    try {
        // Request the latest item list from the Flask application.
        const response = await fetch("/api/items", {
            cache: "no-store"
        });

        // Handle unsuccessful HTTP responses.
        if (!response.ok) {
            throw new Error(`HTTP error: ${response.status}`);
        }

        // Decode the JSON response.
        const data = await response.json();

        // Verify that the response contains an array of items.
        if (!Array.isArray(data.items)) {
            throw new Error("The server returned an invalid item list.");
        }

        // Update every existing product card.
        data.items.forEach(updateAuctionCard);

        // Record the time of the most recent successful refresh.
        console.log("Auction information updated:", new Date().toLocaleTimeString());

    } catch (error) {
        // Log the error without interrupting the user's interaction.
        console.error("Could not refresh auction information:", error);

    } finally {
        // Allow the next refresh request to run.
        refreshInProgress = false;
    }
}


/* Start refreshing immediately and then repeat at regular intervals. */
refreshAuctionData();
setInterval(refreshAuctionData, REFRESH_INTERVAL_MS);
