import os
import time
import json
import threading
import logging
import tempfile
from flask import Flask
from splitter import split_video_into_chunks
from azure.storage.blob import BlobServiceClient
from azure.cosmos import CosmosClient
from azure.servicebus import ServiceBusClient, ServiceBusMessage

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SplitterService")

# --- We only load the connection strings and names as global constants ---
BLOB_CONN_STR = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "").strip()
COSMOS_ENDPOINT = os.getenv("COSMOS_ENDPOINT", "").strip()
COSMOS_KEY = os.getenv("COSMOS_KEY", "").strip()
SERVICE_BUS_CONN_STR = os.getenv("SERVICE_BUS_CONNECTION_STRING", "").strip()

INPUT_QUEUE = os.getenv("SERVICE_BUS_QUEUE", "watermarkqueue")
THUMBNAIL_QUEUE = os.getenv("THUMBNAIL_QUEUE", "thumbnail-queue")
WATERMARK_QUEUE = os.getenv("WATERMARK_QUEUE", "watermark-queue")

COSMOS_DB_NAME = os.getenv("COSMOS_DB_NAME", "watermarkdb")
COSMOS_CONTAINER = os.getenv("COSMOS_CONTAINER", "jobs")

# --- REMOVED: All global client initializations are gone ---

def send_to_queues(job_id, chunk_count):
    """Creates its own client to safely send messages without conflicts."""
    logger.info(f"Sending {chunk_count} messages for job {job_id}...")
    try:
        # Create a short-lived client just for this sending operation.
        with ServiceBusClient.from_connection_string(SERVICE_BUS_CONN_STR) as sb_client:
            # Send to thumbnail queue
            with sb_client.get_queue_sender(queue_name=THUMBNAIL_QUEUE) as sender:
                sender.send_messages(ServiceBusMessage(job_id))
            
            # Send to watermark queue
            with sb_client.get_queue_sender(queue_name=WATERMARK_QUEUE) as sender:
                for i in range(chunk_count):
                    payload = json.dumps({"jobId": job_id, "chunkIndex": i})
                    sender.send_messages(ServiceBusMessage(payload))
        
        logger.info(f"Successfully sent all downstream messages for job {job_id}")
    except Exception as e:
        logger.exception(f"FATAL: Failed to send to queues for job {job_id}: {e}")
        # We need to update the status to failed even if messaging fails
        update_job_status(job_id, "split_failed_messaging")


def update_job_status(job_id, status, chunks=None):
    """Creates its own client to safely update Cosmos DB."""
    try:
        with CosmosClient(COSMOS_ENDPOINT, COSMOS_KEY) as cosmos_client:
            container = cosmos_client.get_database_client(COSMOS_DB_NAME).get_container_client(COSMOS_CONTAINER)
            item = container.read_item(item=job_id, partition_key=job_id)
            item['status'] = status
            if chunks is not None:
                item['chunks'] = chunks
            container.upsert_item(item)
            logger.info(f"Updated Cosmos DB status to '{status}' for job {job_id}")
    except Exception as e:
        logger.exception(f"CRITICAL: Failed to update Cosmos DB status for job {job_id}: {e}")


def process_job(job_id):
    """The main logic for a single job, now fully isolated."""
    logger.info(f"Starting processing for job {job_id}")

    # --- THE ISOLATED DIRECTORY FIX ---
    # Create a unique, temporary directory for this job. It will be auto-deleted.
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            # Create short-lived clients for this specific job
            blob_service_client = BlobServiceClient.from_connection_string(BLOB_CONN_STR)
            
            # Download the video to the unique temporary directory
            video_blob = blob_service_client.get_blob_client(container="videos", blob=f"{job_id}_video.mp4")
            input_path = os.path.join(tmpdir, f"{job_id}.mp4")
            with open(input_path, "wb") as f:
                f.write(video_blob.download_blob().readall())

            # Split video into the unique temporary directory
            output_dir = os.path.join(tmpdir, "chunks")
            split_video_into_chunks(input_path, output_dir)

            # Upload chunks
            chunk_count = 0
            files = os.listdir(output_dir)
            chunk_count = len(files)
            for file in files:
                file_path = os.path.join(output_dir, file)
                chunk_blob_client = blob_service_client.get_blob_client(container="chunks", blob=f"{job_id}/{file}")
                with open(file_path, "rb") as data:
                    chunk_blob_client.upload_blob(data, overwrite=True)
            
            # Update Cosmos DB with the final successful state
            chunks_manifest = [{'index': i, 'status': 'pending'} for i in range(chunk_count)]
            update_job_status(job_id, "split_done", chunks=chunks_manifest)

            # Send messages to the next stage
            send_to_queues(job_id, chunk_count)

        except Exception as e:
            logger.exception(f"Job {job_id} failed during processing.")
            update_job_status(job_id, "split_failed")

def poll_service_bus():
    """The main polling loop. Now simplified."""
    logger.info("Polling Service Bus...")
    while True:
        try:
            # Create a new client for each polling cycle to ensure it's always fresh
            with ServiceBusClient.from_connection_string(SERVICE_BUS_CONN_STR) as sb_client:
                with sb_client.get_queue_receiver(queue_name=INPUT_QUEUE, max_wait_time=5) as receiver:
                    for msg in receiver:
                        try:
                            job_id = str(msg)
                            # "Fire-and-forget": complete the message immediately
                            receiver.complete_message(msg)
                            logger.info(f"Received and acknowledged job: {job_id}")
                            
                            # Start the work in a new thread to not block the receiver
                            threading.Thread(target=process_job, args=(job_id,)).start()
                        except Exception as e:
                            logger.exception(f"Error handling message {msg}: {e}")
        except Exception as e:
            logger.exception("Polling loop failed")
        time.sleep(5) # Wait before creating a new client and polling again

@app.route("/health", methods=["GET"])
def health():
    return {"status": "Splitter container is running"}, 200

if __name__ == "__main__":
    threading.Thread(target=poll_service_bus, daemon=True).start()
    app.run(host="0.0.0.0", port=80)