
/* Refresh the auction data periodically without reloading the page. */

// Define how often the browser should request updated auction data.
const REFRESH_INTERVAL_MS = 3000;

// Request the latest auction information from Flask.
async function refreshAuctionData() {
    try {
        // Ask Flask for the current state of all auction items.
        const response = await fetch("/api/items");

        // Stop if the server reports an unsuccessful response.
        if (!response.ok) {
            throw new Error("Could not retrieve auction data.");
        }

        // Convert the HTTP JSON response into JavaScript data.
        const data = await response.json();

        // Log the latest data for this first integration test.
        // We will use it next to update the product cards on the page.
        console.log("Latest auction items:", data.items);

    } catch (error) {
        // Report errors in the browser console without crashing the page.
        console.error("Auction refresh failed:", error);
    }
}

// Run one request immediately when the page loads.
refreshAuctionData();

// Repeat the request at the configured interval.
setInterval(refreshAuctionData, REFRESH_INTERVAL_MS);
