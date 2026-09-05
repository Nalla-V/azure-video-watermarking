import os
import time
import threading
import logging
import json
from flask import Flask
from azure.servicebus import ServiceBusClient
from aggregator import aggregate_status

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AggregatorService")

# --- We only load the connection strings and names as global constants ---
COSMOS_ENDPOINT = os.getenv("COSMOS_ENDPOINT", "").strip()
COSMOS_KEY = os.getenv("COSMOS_KEY", "").strip()
SERVICE_BUS_CONN_STR = os.getenv("SERVICE_BUS_CONNECTION_STRING", "").strip()
AGGREGATOR_QUEUE = os.getenv("AGGREGATOR_QUEUE", "status-aggregator-queue").strip()

# REMOVED: The global sb_client is gone.

def poll_aggregator_queue():
    logger.info(f"Polling {AGGREGATOR_QUEUE} for status updates...")
    while True:
        try:
            # Create a short-lived client just for this polling cycle.
            with ServiceBusClient.from_connection_string(SERVICE_BUS_CONN_STR) as sb_client:
                with sb_client.get_queue_receiver(queue_name=AGGREGATOR_QUEUE, max_wait_time=5) as receiver:
                    for msg in receiver:
                        try:
                            # "Fire and forget" pattern
                            body = json.loads(b"".join(msg.body).decode("utf-8"))
                            
                            # Immediately complete the message.
                            receiver.complete_message(msg)
                            logger.info(f"Received and acknowledged update: {body}")
                            
                            # Start the aggregation logic in a new thread to keep the poller responsive.
                            threading.Thread(
                                target=aggregate_status,
                                args=(body, COSMOS_ENDPOINT, COSMOS_KEY, SERVICE_BUS_CONN_STR)
                            ).start()

                        except Exception as e:
                            logger.exception(f"Error handling message: {msg}. Error: {e}")
        except Exception as e:
            logger.exception(f"Polling loop failed: {e}")
        time.sleep(5)

@app.route("/health", methods=["GET"])
def health():
    return {"status": "Aggregator container is running"}, 200

if __name__ == "__main__":
    threading.Thread(target=poll_aggregator_queue, daemon=True).start()
    app.run(host="0.0.0.0", port=80)