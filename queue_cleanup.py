import os
import time
import logging
# THE FIRST FIX: Import the required Enum object
from azure.servicebus import ServiceBusClient, ServiceBusSubQueue

# --- Configuration ---
# Load the Service Bus connection string from an environment variable
SERVICE_BUS_CONN_STR = os.getenv("SERVICE_BUS_CONNECTION_STRING")

# THE SECOND FIX: Update this list to match all your queues from the screenshot
QUEUES_TO_CLEAR = [
    "encode-queue",
    "status-aggregator-queue",
    "thumbnail-queue",
    "watermark-queue",
    "watermarkqueue"
]
# ---------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("QueueCleaner")

def drain_sub_queue(sb_client, queue_name, sub_queue):
    """Drains all messages from a given sub-queue (e.g., active or dead-letter)."""
    messages_cleared = 0
    # Determine the name for logging purposes
    sub_queue_name_for_log = "Dead-Letter" if sub_queue else "Active"
    
    logger.info(f"-> Checking {sub_queue_name_for_log} messages in '{queue_name}'...")
    
    while True:
        try:
            with sb_client.get_queue_receiver(queue_name=queue_name, sub_queue=sub_queue, max_wait_time=2) as receiver:
                messages = receiver.receive_messages(max_message_count=100)
                
                if not messages:
                    logger.info(f"   -> {sub_queue_name_for_log} queue is empty.")
                    break 
                
                for msg in messages:
                    receiver.complete_message(msg)
                    messages_cleared += 1
                    if messages_cleared > 0 and messages_cleared % 100 == 0:
                        logger.info(f"   Cleared {messages_cleared} messages so far from {sub_queue_name_for_log}...")
            # Brief pause to prevent overly aggressive looping if there's an issue
            time.sleep(0.1)
        except Exception as e:
            logger.error(f"   An error occurred while receiving from {sub_queue_name_for_log}: {e}")
            break # Exit loop on error to prevent infinite loops
            
    return messages_cleared

def clear_full_queue(connection_string: str, queue_name: str):
    """Clears both active and dead-letter messages from a queue."""
    logger.info(f"--- Processing queue: {queue_name} ---")
    
    try:
        with ServiceBusClient.from_connection_string(connection_string) as sb_client:
            active_cleared = drain_sub_queue(sb_client, queue_name, sub_queue=None)
            
            # THE THIRD FIX: Use the official Enum member instead of a string
            dlq_cleared = drain_sub_queue(sb_client, queue_name, sub_queue=ServiceBusSubQueue.DEAD_LETTER)
            
        total = active_cleared + dlq_cleared
        logger.info(f"--- Finished with '{queue_name}'. Total messages cleared: {total} ---")
        
    except Exception as e:
        logger.error(f"An error occurred while clearing queue '{queue_name}': {e}", exc_info=True)


if __name__ == "__main__":
    if not SERVICE_BUS_CONN_STR:
        logger.error("FATAL: SERVICE_BUS_CONNECTION_STRING environment variable is not set.")
    else:
        logger.info("Starting Service Bus queue cleanup process.")
        for queue in QUEUES_TO_CLEAR:
            clear_full_queue(SERVICE_BUS_CONN_STR, queue)
            time.sleep(1) 
        logger.info("All specified queues have been processed.")