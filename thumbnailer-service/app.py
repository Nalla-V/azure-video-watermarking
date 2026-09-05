import os
import time
import threading
import logging
import json
import tempfile
from flask import Flask
# <<< THE FIX IS HERE: The missing import is added back >>>
from azure.storage.blob import BlobServiceClient
from azure.servicebus import ServiceBusClient, ServiceBusMessage
from thumbnailer import generate_composite_thumbnail

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ThumbnailerService")

# Load environment variables
BLOB_CONN_STR = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "").strip()
SERVICE_BUS_CONN_STR = os.getenv("SERVICE_BUS_CONNECTION_STRING", "").strip()
THUMBNAIL_QUEUE = os.getenv("THUMBNAIL_QUEUE", "thumbnail-queue")
AGGREGATOR_QUEUE = os.getenv("NEXT_QUEUE", "status-aggregator-queue")

# No global clients are needed

def poll_thumbnail_queue():
    logger.info("Polling thumbnail-queue for jobs...")
    while True:
        try:
            with ServiceBusClient.from_connection_string(SERVICE_BUS_CONN_STR) as sb_client:
                with sb_client.get_queue_receiver(queue_name=THUMBNAIL_QUEUE, max_wait_time=5) as receiver:
                    for msg in receiver:
                        try:
                            job_id = b"".join(msg.body).decode("utf-8")
                            receiver.complete_message(msg)
                            logger.info(f"Received and acknowledged job_id: {job_id}. Starting process...")
                            
                            threading.Thread(target=process_job, args=(job_id,)).start()
                        except Exception as e:
                            logger.exception(f"Error handling message: {msg}. Error: {e}")
        except Exception as e:
            logger.exception(f"Polling loop failed: {e}")
        time.sleep(5)

def process_job(job_id):
    status = "completed"
    try:
        # Create short-lived clients inside the function for thread safety
        blob_service = BlobServiceClient.from_connection_string(BLOB_CONN_STR)
        
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_chunk_dir = os.path.join(tmpdir, "chunks")
            os.makedirs(temp_chunk_dir, exist_ok=True)
            chunk_paths = []

            container = blob_service.get_container_client("chunks")
            blob_list = list(container.list_blobs(name_starts_with=f"{job_id}/"))
            if not blob_list:
                raise Exception(f"No video chunks found for job {job_id}")

            sorted_blobs = sorted(blob_list, key=lambda b: b.name)
            for blob in sorted_blobs:
                local_path = os.path.join(temp_chunk_dir, os.path.basename(blob.name))
                with open(local_path, "wb") as f:
                    blob_client = container.get_blob_client(blob.name)
                    blob_client.download_blob().readinto(f)
                chunk_paths.append(local_path)

            output_path = os.path.join(tmpdir, f"{job_id}_thumbnail.png")
            generate_composite_thumbnail(chunk_paths, output_path)

            output_container = blob_service.get_container_client("output")
            try:
                output_container.create_container()
            except Exception:
                pass 
            with open(output_path, "rb") as data:
                output_container.upload_blob(name=f"{job_id}_thumbnail.png", data=data, overwrite=True)
            logger.info(f"Uploaded thumbnail for job {job_id}")

    except Exception as e:
        logger.exception(f"Thumbnail generation failed for job {job_id}")
        status = "failed"
    finally:
        try:
            with ServiceBusClient.from_connection_string(SERVICE_BUS_CONN_STR) as sb_client:
                with sb_client.get_queue_sender(queue_name=AGGREGATOR_QUEUE) as sender:
                    message_body = json.dumps({"jobId": job_id, "type": "thumbnail", "status": status})
                    sender.send_messages(ServiceBusMessage(message_body))
                    logger.info(f"Sent status '{status}' to aggregator for job {job_id}")
        except Exception as e:
            logger.exception(f"CRITICAL: Failed to send status to aggregator for job {job_id}: {e}")

@app.route("/health", methods=["GET"])
def health():
    return {"status": "Thumbnailer container is running"}, 200

if __name__ == "__main__":
    threading.Thread(target=poll_thumbnail_queue, daemon=True).start()
    app.run(host="0.0.0.0", port=80)