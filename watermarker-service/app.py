import os
import time
import threading
import logging
import json
from flask import Flask
# This is the only import needed from Service Bus here
from azure.servicebus import ServiceBusClient
from watermarker import watermark_chunk

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("WatermarkerService")

# We only load connection strings and names as global constants.
BLOB_CONN_STR = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "").strip()
SERVICE_BUS_CONN_STR = os.getenv("SERVICE_BUS_CONNECTION_STRING", "").strip()
WATERMARK_QUEUE = os.getenv("WATERMARK_QUEUE", "watermark-queue")
AGGREGATOR_QUEUE = os.getenv("AGGREGATOR_QUEUE", "status-aggregator-queue")

# The global sb_client is removed to prevent concurrency bugs.

def poll_watermark_queue():
    logger.info(f"Polling {WATERMARK_QUEUE} for jobs...")
    while True:
        try:
            # A new, temporary client is created for each polling cycle. This is thread-safe.
            with ServiceBusClient.from_connection_string(SERVICE_BUS_CONN_STR) as sb_client:
                with sb_client.get_queue_receiver(queue_name=WATERMARK_QUEUE, max_wait_time=5) as receiver:
                    for msg in receiver:
                        try:
                            # --- This is the "Fire and Forget" Pattern ---
                            # 1. Decode the message
                            body = json.loads(b"".join(msg.body).decode("utf-8"))
                            job_id = body["jobId"]
                            chunk_index = body["chunkIndex"]
                            
                            # 2. Immediately complete it from the queue
                            receiver.complete_message(msg)
                            logger.info(f"Received and acknowledged job: {job_id}, chunk: {chunk_index}")
                            
                            # 3. Start the long-running task in a separate thread
                            threading.Thread(
                                target=watermark_chunk,
                                args=(job_id, chunk_index, BLOB_CONN_STR, SERVICE_BUS_CONN_STR, AGGREGATOR_QUEUE)
                            ).start()

                        except Exception as e:
                            logger.exception(f"Error handling message: {msg}. Error: {e}")
        except Exception as e:
            logger.exception(f"Polling loop failed: {e}")
        time.sleep(5)

@app.route("/health", methods=["GET"])
def health():
    return {"status": "Watermarker container is running"}, 200

if __name__ == "__main__":
    threading.Thread(target=poll_watermark_queue, daemon=True).start()
    app.run(host="0.0.0.0", port=80)