import json
import os
from azure.cosmos import CosmosClient, exceptions
from azure.servicebus import ServiceBusClient, ServiceBusMessage

ENCODE_QUEUE = os.getenv("ENCODE_QUEUE", "encode-queue")

def aggregate_status(body, cosmos_endpoint, cosmos_key, service_bus_connection):
    job_id = body["jobId"]
    update_type = body["type"]
    status = body["status"]
    
    print(f"Aggregator received: job='{job_id}', type='{update_type}', status='{status}'")

    # --- THE FIX IS HERE: Create a short-lived client inside the function ---
    with CosmosClient(cosmos_endpoint, cosmos_key) as cosmos_client:
        container = cosmos_client.get_database_client('watermarkdb').get_container_client('jobs')
        
        # This logic is now safely encapsulated.
        try:
            # First, check for the 'split' type to create the initial document
            if update_type == 'split':
                if status == 'split_done':
                    print(f"Creating new job document for {job_id}")
                    initial_item = {
                        'id': job_id, 'job_id': job_id, 'status': status,
                        'chunks': [{'index': i, 'status': 'pending'} for i in range(body.get('chunkCount', 0))]
                    }
                    container.create_item(body=initial_item)
                    print(f"Successfully created initial document for job {job_id}.")
                else: # split_failed
                    item = container.read_item(item=job_id, partition_key=job_id)
                    item['status'] = 'split_failed'
                    container.upsert_item(body=item)
                return # The job of this message is done.

            # For all other updates, patch the existing document
            patch_operations = []
            if update_type == 'watermark':
                chunk_index = body.get("chunkIndex")
                patch_operations.append({'op': 'replace', 'path': f'/chunks/{chunk_index}/status', 'value': status})
            elif update_type == 'thumbnail':
                patch_operations.append({'op': 'set', 'path': '/thumbnailStatus', 'value': status})
            elif update_type == 'encode':
                patch_operations.append({'op': 'set', 'path': '/status', 'value': status})
                if status == 'completed':
                    patch_operations.append({'op': 'set', 'path': '/output_blob', 'value': body.get("output_blob")})
            
            if patch_operations:
                container.patch_item(item=job_id, partition_key=job_id, patch_operations=patch_operations)
                print(f"Successfully patched job {job_id} for update type '{update_type}'.")

            # After patching, read the item back to check the new overall state
            item = container.read_item(item=job_id, partition_key=job_id)
            
            # Recalculate and patch the 'details' string
            total_chunks = len(item.get('chunks', []))
            watermarked_count = sum(1 for c in item.get('chunks', []) if c.get('status') == 'completed - WM')
            details_string = f'Watermarked {watermarked_count}/{total_chunks} chunks. Thumbnail: {item.get("thumbnailStatus", "pending")}'
            container.patch_item(item=job_id, partition_key=job_id, patch_operations=[{'op': 'set', 'path': '/details', 'value': details_string}])
            print(f"Updated details for job {job_id}: \"{details_string}\"")

            # Check if it's time to trigger the encoder
            all_chunks_watermarked = (watermarked_count == total_chunks) and (total_chunks > 0)
            thumbnail_complete = item.get('thumbnailStatus') == 'completed'

            if item.get('status') == 'split_done' and all_chunks_watermarked and thumbnail_complete:
                print(f"ALL prerequisites for job {job_id} are complete. Triggering final encoding.")
                container.patch_item(item=job_id, partition_key=job_id, patch_operations=[{'op': 'set', 'path': '/status', 'value': 'encoding'}])
                
                # Create a temporary client to send the final message
                with ServiceBusClient.from_connection_string(service_bus_connection) as sb_client:
                    with sb_client.get_queue_sender(ENCODE_QUEUE) as sender:
                        message_body = json.dumps({'jobId': job_id})
                        sender.send_messages(ServiceBusMessage(message_body))
                        print(f"Message sent to {ENCODE_QUEUE} for job {job_id}.")

        except exceptions.CosmosResourceNotFoundError:
            print(f"ERROR: Tried to access a non-existent job: {job_id}. Splitter may have failed.")
            return
        except Exception as e:
            print(f"An unexpected error occurred in the aggregator logic: {e}")
            # Consider sending a "failed" status update here if appropriate