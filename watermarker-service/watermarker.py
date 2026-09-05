import av
import json
import io
import logging
from PIL import Image
from azure.storage.blob import BlobServiceClient
from azure.servicebus import ServiceBusClient, ServiceBusMessage

logger = logging.getLogger("WatermarkerService")

# UPDATED: The function signature accepts aggregator_queue_name
def watermark_chunk(job_id, chunk_index, connection_string, service_bus_connection, aggregator_queue_name):
    logger.info(f"Watermarker logic started for job_id: {job_id}, chunk_index: {chunk_index}")
    status_to_report = 'completed - WM'

    try:
        # This entire try block contains YOUR original, working logic.
        blob_service_client = BlobServiceClient.from_connection_string(connection_string)
        uploads_container = blob_service_client.get_container_client('videos')
        chunks_container = blob_service_client.get_container_client('chunks')
        watermarked_container = blob_service_client.get_container_client('watermarked')

        try:
            watermarked_container.create_container()
        except Exception:
            logger.info("Container 'watermarked' already exists, continuing.")

        watermark_blob = uploads_container.get_blob_client(f'{job_id}_watermark.png')
        watermark_stream = io.BytesIO(watermark_blob.download_blob().readall())
        watermark_img = Image.open(watermark_stream).convert("RGBA")

        input_blob_path = f'{job_id}/chunk_{chunk_index:03}.mp4'
        logger.info(f"Downloading chunk blob: {input_blob_path}")
        input_blob = chunks_container.get_blob_client(input_blob_path)
        input_stream = io.BytesIO(input_blob.download_blob().readall())

        output_stream = io.BytesIO()
        
        with av.open(input_stream) as input_container:
            input_stream_video = input_container.streams.video[0] 
            with av.open(output_stream, mode='w', format='mp4') as output_container:
                output_video_stream = output_container.add_stream(input_stream_video.codec_context.name)
                output_video_stream.time_base = input_stream_video.time_base

                w_width, w_height = watermark_img.size
                ratio = w_width / w_height
                new_w_width = input_stream_video.width // 5
                new_w_height = int(new_w_width / ratio)
                watermark_resized = watermark_img.resize((new_w_width, new_w_height), Image.Resampling.LANCZOS)

                for frame in input_container.decode(video=0):
                    pil_frame = frame.to_image().convert("RGBA")
                    position = (pil_frame.width - watermark_resized.width - 10, 10)
                    pil_frame.paste(watermark_resized, position, watermark_resized)
                    pil_frame = pil_frame.convert("RGB")
                    new_frame = av.VideoFrame.from_image(pil_frame)
                    new_frame.pts = frame.pts
                    for packet in output_video_stream.encode(new_frame):
                        output_container.mux(packet)
                for packet in output_video_stream.encode():
                    output_container.mux(packet)

        output_stream.seek(0)
        output_blob_name = f'{job_id}_watermarked_{chunk_index}.mp4'
        logger.info(f"Uploading to blob: watermarked/{output_blob_name}")
        watermarked_container.upload_blob(name=output_blob_name, data=output_stream, overwrite=True)
        logger.info(f"✅ Successfully uploaded {output_blob_name}")

    except Exception as e:
        logger.exception(f"FATAL: Failed to watermark chunk {chunk_index}. Error: {e}")
        status_to_report = 'failed'

    finally:
        logger.info(f"Sending status '{status_to_report}' to aggregator queue for chunk {chunk_index}")
        # This logic is now self-contained and safe
        with ServiceBusClient.from_connection_string(service_bus_connection) as sb_client:
            # UPDATED: Uses the passed-in aggregator_queue_name for consistency
            with sb_client.get_queue_sender(aggregator_queue_name) as sender:
                message_body = json.dumps({
                    'jobId': job_id,
                    'type': 'watermark',
                    'chunkIndex': chunk_index,
                    'status': status_to_report
                })
                sender.send_messages(ServiceBusMessage(message_body))