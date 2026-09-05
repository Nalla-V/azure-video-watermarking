import os
import time
import threading
import logging
import json
from flask import Flask
from azure.servicebus import ServiceBusClient
from encoder import encode_chunks

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("EncoderService")

# --- We only load the connection strings and names as global constants ---
BLOB_CONN_STR = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "").strip()
SERVICE_BUS_CONN_STR = os.getenv("SERVICE_BUS_CONNECTION_STRING", "").strip()
ENCODE_QUEUE = os.getenv("ENCODE_QUEUE", "encode-queue").strip()
AGGREGATOR_QUEUE = os.getenv("AGGREGATOR_QUEUE", "status-aggregator-queue").strip()

# REMOVED: The global sb_client is gone.

def poll_encode_queue():
    logger.info(f"Polling {ENCODE_QUEUE} for jobs...")
    while True:
        try:
            # Create a short-lived client just for this polling cycle.
            with ServiceBusClient.from_connection_string(SERVICE_BUS_CONN_STR) as sb_client:
                with sb_client.get_queue_receiver(queue_name=ENCODE_QUEUE, max_wait_time=5) as receiver:
                    for msg in receiver:
                        try:
                            # "Fire and forget" pattern
                            body = json.loads(b"".join(msg.body).decode("utf-8"))
                            job_id = body["jobId"]
                            
                            receiver.complete_message(msg)
                            logger.info(f"Received and acknowledged encoding job_id={job_id}. Starting process...")
                            
                            # Start the work in a new thread to handle multiple jobs in parallel
                            # without blocking the message receiver.
                            threading.Thread(
                                target=encode_chunks,
                                args=(job_id, BLOB_CONN_STR, SERVICE_BUS_CONN_STR, AGGREGATOR_QUEUE)
                            ).start()

                        except Exception as e:
                            logger.exception(f"Error handling message: {msg}. Error: {e}")
        except Exception as e:
            logger.exception(f"Polling loop failed: {e}")
        time.sleep(5)

@app.route("/health", methods=["GET"])
def health():
    return {"status": "Encoder container is running"}, 200

if __name__ == "__main__":
    threading.Thread(target=poll_encode_queue, daemon=True).start()
    app.run(host="0.0.0.0", port=80)