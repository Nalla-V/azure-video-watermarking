import os
import logging
import tempfile
import time
import json
from azure.storage.blob import BlobServiceClient
from azure.servicebus import ServiceBusClient, ServiceBusMessage
from moviepy.editor import VideoFileClip, concatenate_videoclips

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("EncoderService")

def encode_chunks(job_id, blob_conn_str, service_bus_connection, aggregator_queue_name):
    status = "completed"
    output_blob_name = f"{job_id}_output.mp4"
    
    # Create a unique, temporary directory for this specific encoding job.
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            # Create short-lived clients inside the function for thread safety.
            blob_service_client = BlobServiceClient.from_connection_string(blob_conn_str)
            input_container = blob_service_client.get_container_client("watermarked")
            output_container = blob_service_client.get_container_client("output")

            logger.info(f"Processing encoding for job_id={job_id}")

            # Resiliently wait for all watermarked blobs to appear
            max_retries = 5
            for attempt in range(max_retries):
                blob_list = list(input_container.list_blobs(name_starts_with=job_id))
                if blob_list:
                    logger.info(f"Found {len(blob_list)} watermarked chunks.")
                    break
                logger.warning(f"Attempt {attempt + 1}: No watermarked chunks found yet. Waiting...")
                time.sleep(4)
            
            if not blob_list:
                raise ValueError(f"After {max_retries} attempts, no input chunks found for job {job_id}.")

            sorted_blob_list = sorted(blob_list, key=lambda b: int(b.name.split('_')[-1].split('.')[0]))

            chunk_paths = []
            for blob_data in sorted_blob_list:
                download_path = os.path.join(tmpdir, blob_data.name.split('/')[-1])
                logger.info(f"Downloading {blob_data.name} to {download_path}")
                blob_client = input_container.get_blob_client(blob_data.name)
                with open(download_path, "wb") as f:
                    f.write(blob_client.download_blob().readall())
                chunk_paths.append(download_path)

            logger.info("Merging chunks using MoviePy")
            clips = [VideoFileClip(path) for path in chunk_paths]
            final_clip = concatenate_videoclips(clips, method="compose")
            final_output_path = os.path.join(tmpdir, output_blob_name)
            final_clip.write_videofile(final_output_path, codec="libx264", preset="medium", logger='bar')
            for clip in clips:
                clip.close()
            final_clip.close()

            logger.info(f"Uploading final video as {output_blob_name}")
            with open(final_output_path, "rb") as f:
                output_container.upload_blob(name=output_blob_name, data=f, overwrite=True)

        except Exception as e:
            logger.exception(f"FATAL: Encoder failed for job {job_id}. Error: {e}")
            status = "failed"
    
    try:
        logger.info(f"Sending final status '{status}' to aggregator queue '{aggregator_queue_name}' for job {job_id}")
        with ServiceBusClient.from_connection_string(service_bus_connection) as sb_client:
            with sb_client.get_queue_sender(aggregator_queue_name) as sender:
                message_body = json.dumps({
                    "jobId": job_id,
                    "type": "encode",
                    "status": status,
                    "output_blob": output_blob_name if status == "completed" else None
                })
                sender.send_messages(ServiceBusMessage(message_body))
    except Exception as e:
        logger.exception(f"CRITICAL: Failed to send status to aggregator for job {job_id}: {e}")

    logger.info(f"Encoder process finished for job_id={job_id}.")