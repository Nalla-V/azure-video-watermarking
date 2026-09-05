# --- START OF THE TRULY COMPLETE AND CORRECTED app.py ---
import os
import sys
import logging
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from azure.storage.blob import BlobServiceClient
from azure.cosmos import CosmosClient, PartitionKey, exceptions as cosmos_exceptions
from azure.servicebus import ServiceBusClient, ServiceBusMessage
from azure.servicebus.exceptions import ServiceBusError 
from azure.core.exceptions import ResourceExistsError, AzureError

# Enhanced logging configuration
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("WatermarkApp")
logger.setLevel(logging.INFO)
azure_logger = logging.getLogger("azure")
azure_logger.setLevel(logging.INFO)

def create_app():
    app = Flask(__name__)
    logger.info("Application factory starting.")

    # CORS configuration
    CORS(app, resources={r"/api/*": {"origins": ["https://watermarkstorage12345.z6.web.core.windows.net"]}})

    # --- Configuration and Client Initialization is unchanged ---
    try:
        app.config['AZURE_STORAGE_CONNECTION_STRING'] = os.environ['AZURE_STORAGE_CONNECTION_STRING']
        app.config['COSMOS_ENDPOINT'] = os.environ['COSMOS_ENDPOINT']
        app.config['COSMOS_KEY'] = os.environ['COSMOS_KEY']
        app.config['SERVICE_BUS_CONNECTION'] = os.environ['SERVICE_BUS_CONNECTION']
        logger.info("Successfully loaded all Azure environment variables.")
    except KeyError as e:
        logger.critical(f"FATAL: Missing required environment variable: {e}")
        sys.exit(f"FATAL: Missing required environment variable: {e}")

    try:
        logger.info("Initializing Azure clients...")
        blob_service_client = BlobServiceClient.from_connection_string(app.config['AZURE_STORAGE_CONNECTION_STRING'])
        cosmos_client = CosmosClient(app.config['COSMOS_ENDPOINT'], app.config['COSMOS_KEY'])
        servicebus_client = ServiceBusClient.from_connection_string(conn_str=app.config['SERVICE_BUS_CONNECTION'])

        app.config['BLOB_SERVICE_CLIENT'] = blob_service_client
        app.config['SERVICEBUS_CLIENT'] = servicebus_client
        
        logger.info("Azure clients initialized successfully.")

        DB_NAME = 'watermarkdb'
        COLLECTION_NAME = 'jobs'
        database = cosmos_client.create_database_if_not_exists(DB_NAME)
        app.config['COSMOS_CONTAINER'] = database.create_container_if_not_exists(id=COLLECTION_NAME, partition_key=PartitionKey(path="/job_id"))
        
        app.config['VIDEO_CONTAINER_CLIENT'] = blob_service_client.get_container_client("videos")
        app.config['OUTPUT_CONTAINER_CLIENT'] = blob_service_client.get_container_client("output")
        
        try:
            app.config['VIDEO_CONTAINER_CLIENT'].create_container()
            logger.info("Blob container 'videos' was created.")
        except ResourceExistsError:
            logger.info("Blob container 'videos' already exists, no action taken.")

        try:
            app.config['OUTPUT_CONTAINER_CLIENT'].create_container()
            logger.info("Blob container 'output' was created.")
        except ResourceExistsError:
            logger.info("Blob container 'output' already exists, no action taken.")

        logger.info("Azure resources (DB, containers) are ready.")
    except Exception as e:
        logger.exception("FATAL: A failure occurred during Azure client initialization.")
        sys.exit("FATAL: Could not initialize Azure clients.")

    
    # --- /api/upload is unchanged ---
    @app.route('/api/upload', methods=['POST'])
    def upload():
        job_id = request.form.get('job_id')
        logger.info(f"Received upload request for job_id: {job_id}")
        video = request.files.get('video')
        watermark = request.files.get('watermark')

        if not job_id or not video or not watermark:
            logger.error(f"Upload failed for job_id '{job_id}': Missing form data.")
            return jsonify({"error": "Missing job_id, video or watermark"}), 400
        
        try:
            video_container = app.config['VIDEO_CONTAINER_CLIENT']
            cosmos_container = app.config['COSMOS_CONTAINER']
            servicebus_client = app.config['SERVICEBUS_CLIENT']
            
            video_blob_name = f"{job_id}_video.mp4"
            watermark_blob_name = f"{job_id}_watermark.png"
            
            logger.info(f"Step 1/4: Uploading video blob: {video_blob_name}")
            video_container.upload_blob(name=video_blob_name, data=video, overwrite=True)
            video_url = video_container.url + '/' + video_blob_name
            
            logger.info(f"Step 2/4: Uploading watermark blob: {watermark_blob_name}")
            video_container.upload_blob(name=watermark_blob_name, data=watermark, overwrite=True)
            watermark_url = video_container.url + '/' + watermark_blob_name
            
            logger.info(f"Step 3/4: Updating Cosmos DB for job_id: {job_id}")
            cosmos_container.upsert_item({
                "id": job_id, "job_id": job_id, "status": "uploaded",
                "video_url": video_url, "watermark_url": watermark_url
            })

            logger.info(f"Step 4/4: Sending message to Service Bus for job_id: {job_id}")
            sender = servicebus_client.get_queue_sender(queue_name="watermarkqueue")
            with sender:
                message = ServiceBusMessage(job_id)
                sender.send_messages(message, timeout=60)
            
            logger.info(f"Successfully processed and queued job_id: {job_id}")
            return jsonify({"message": "Files uploaded successfully"}), 200

        except ServiceBusError as e:
            logger.exception(f"A Service Bus error occurred for job_id: {job_id}.")
            return jsonify({"error": "The request timed out or failed while communicating with the processing queue. Please check the job status in a moment."}), 504
        except AzureError as e:
            logger.exception(f"An Azure SDK error occurred during upload for job_id: {job_id}")
            return jsonify({"error": f"An Azure service error occurred: {e}"}), 500
        except Exception as e:
            logger.exception(f"An unexpected non-Azure error occurred during upload for job_id: {job_id}")
            return jsonify({"error": "An unexpected server error occurred."}), 500

    # --- /api/status is unchanged ---
    @app.route('/api/status/<job_id>', methods=['GET'])
    def check_status(job_id):
        try:
            cosmos_container = app.config['COSMOS_CONTAINER']
            item_response = cosmos_container.read_item(item=job_id, partition_key=job_id)
            return jsonify({"job_id": job_id, "status": item_response.get("status", "unknown")})
        except cosmos_exceptions.CosmosResourceNotFoundError:
            return jsonify({"error": "Job ID not found"}), 404
        except Exception as e:
            logger.exception(f"An unexpected error occurred during status check for job_id: {job_id}")
            return jsonify({"error": str(e)}), 500

    # --- /api/download is unchanged and works for the video ---
    @app.route('/api/download/<job_id>', methods=['GET'])
    def download(job_id):
        try:
            output_container = app.config['OUTPUT_CONTAINER_CLIENT']
            blob_name = f"{job_id}_output.mp4"
            blob_client = output_container.get_blob_client(blob_name)

            if not blob_client.exists():
                logger.warning(f"Download request for job_id {job_id}, but output file not found.")
                return jsonify({"error": "Processed file not available yet"}), 404

            file_path = f"/tmp/{blob_name}"
            with open(file_path, "wb") as file:
                file.write(blob_client.download_blob().readall())

            logger.info(f"Serving download for job_id {job_id}.")
            return send_file(file_path, as_attachment=True)
        except Exception as e:
            logger.exception(f"An unexpected error occurred during download for job_id: {job_id}")
            return jsonify({"error": str(e)}), 500

    # --- START OF THE NEW THUMBNAIL DOWNLOAD ENDPOINT ---
    @app.route('/api/thumbnail/<job_id>', methods=['GET'])
    def download_thumbnail(job_id):
        logger.info(f"Thumbnail download request for job_id {job_id}")
        try:
            output_container = app.config['OUTPUT_CONTAINER_CLIENT']
            blob_name = f"{job_id}_thumbnail.png"
            blob_client = output_container.get_blob_client(blob_name)

            if not blob_client.exists():
                logger.warning(f"Thumbnail '{blob_name}' not found for job_id {job_id}.")
                return jsonify({"error": "Thumbnail file not available."}), 404
            
            file_path = f"/tmp/{blob_name}"
            with open(file_path, "wb") as file:
                file.write(blob_client.download_blob().readall())

            logger.info(f"Serving download for thumbnail: {blob_name}")
            return send_file(file_path, as_attachment=True)
            
        except Exception as e:
            logger.exception(f"An unexpected error occurred during thumbnail download for job_id: {job_id}")
            return jsonify({"error": "An server error occurred during thumbnail download."}), 500
    # --- END OF THE NEW THUMBNAIL DOWNLOAD ENDPOINT ---

    # --- /api/health is unchanged ---
    @app.route('/api/health', methods=['GET'])
    def health():
        return jsonify({"message": "Welcome to Watermark API"})

    logger.info("Application factory finished successfully.")
    return app

# This final line allows Gunicorn to find and run the app
app = create_app()

if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0", port=8000)