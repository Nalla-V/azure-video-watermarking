# Video Watermarking as a Service

A distributed video watermarking pipeline on Azure. Users upload an MP4 and a
watermark image through a web interface; the video is split into chunks,
watermarked in parallel, thumbnailed, reassembled, and made available for
download, with job progress visible throughout.

The design point is that there is no load balancer and no scaling controller.
Five stateless services coordinate entirely through Service Bus queues and a
shared Cosmos DB job record, and Azure scales each one on its own queue depth.

> **This deployment is no longer live.** The Azure resources were removed when
> the course subscription ended, so the frontend URL and API endpoints in the
> code no longer resolve. The code, architecture and measurements are intact.

## Architecture

```
React UI ──> Flask API ──> Blob Storage (video, watermark)
                 │              │
                 │              └──> Cosmos DB (job record)
                 v
          splitter-queue
                 │
                 v
           Splitter ──> chunks in Blob
                 │
        ┌────────┴────────┐
        v                 v
 watermark-queue   thumbnail-queue
        │                 │
        v                 v
   Watermarker       Thumbnailer
        │                 │
        └────────┬────────┘
                 v
         aggregator-queue
                 │
                 v
           Aggregator ──> encoder-queue ──> Encoder ──> final video in Blob
```

**Splitter** — downloads the uploaded video, cuts it into 15-second chunks,
uploads them, and fans out one message per chunk to the watermark queue plus one
to the thumbnail queue.

**Watermarker** — applies the watermark to every frame of one chunk. Runs in
parallel across chunks and in parallel with the Thumbnailer.

**Thumbnailer** — takes the first unmodified frame from each chunk and composes
them into a single summary image.

**Aggregator** — the only stateful decision point. Tracks per-chunk and
thumbnail completion in Cosmos DB and triggers the Encoder once everything is
done.

**Encoder** — concatenates the watermarked chunks into the final output.

### Design decisions worth noting

**Fire-and-forget message handling.** Every worker acknowledges its Service Bus
message immediately on receipt, before doing the work. Video processing takes
longer than the message lock duration, so holding the lock until completion
causes lock expiry and duplicate delivery. Acknowledging early trades
at-least-once delivery for at-most-once, which is safe here because output blobs
are idempotent — reprocessing a chunk overwrites it with the same result.

**One coordinator, not many.** Only the Aggregator writes job-level progress.
Letting each worker update the shared counter would mean concurrent
read-modify-write on the same Cosmos document, so the completion logic lives in
one place.

**Blob storage as the transport.** Nothing is passed in memory or over local
disk between services; every intermediate artefact is a blob. That is what makes
the workers genuinely stateless and independently scalable.

**FFmpeg baked into each image.** Every service Dockerfile carries its own
FFmpeg runtime rather than relying on the host, which was the fix for import
failures on the managed platform.

## Azure services

| Service | Role |
|---|---|
| Blob Storage | static frontend, uploads, chunks, outputs |
| App Service | Flask API (`/upload`, `/status`, `/download`) |
| Service Bus | five queues, one per pipeline stage |
| Cosmos DB | job metadata and progress, partitioned by `job_id` |
| Container Apps | the five worker services |
| Container Registry | worker images |

Scaling is configured per Container App as a Service Bus queue-length rule. This
cannot be set from the Azure Portal, so it needs the CLI:

```bash
az containerapp update \
  --name watermarker-app \
  --resource-group <resource-group> \
  --scale-rules servicebus-rule=type=azure-servicebus-queue \
    queueName=<queue> namespace=<namespace> queueLength=5 \
    auth=connection-string \
    connectionStringSecretRef=SERVICE_BUS_CONNECTION
```

## Results

End-to-end latency, upload to output available, averaged over three runs:

| Video | 1 container | 2 containers |
|---|---|---|
| 30 s | 2:23 | 2:06 |
| 60 s | 4:47 | 3:54 |

Throughput, two jobs submitted simultaneously:

| Video | 1 container | 2 containers |
|---|---|---|
| 30 s | 4:15 | 3:45 |
| 60 s | 9:27 | 8:24 |

The second worker helps more on the longer video (53 s saved, against 17 s on
the short one), which follows from chunking: a 60-second video splits into four
chunks that can genuinely run in parallel, while a 30-second video splits into
two and spends proportionally more time in the serial stages — upload, split and
final encode — that no amount of watermarker parallelism touches.

## Configuration

Both config files are excluded from this repository because they hold live
credentials. Copy the examples and fill in your own:

```bash
cp local.settings.example.json local.settings.json
cp appsettings.example.json appsettings.json
```

Required values: `AZURE_STORAGE_CONNECTION_STRING`, `COSMOS_ENDPOINT`,
`COSMOS_KEY`, `SERVICE_BUS_CONNECTION`. In Azure these are set as environment
variables on the App Service and on each Container App rather than from a file.

## Deployment

**Frontend** — build and upload to the storage account's `$web` container:

```bash
npm run build
azcopy copy "build/*" "https://<storage-account>.blob.core.windows.net/\$web?<sas>" --recursive=true
```

**Flask API** — zip deploy to App Service, with Gunicorn as the startup command:

```bash
az webapp deploy --resource-group <rg> --name <app-name> --src-path flask-backend.zip --type zip
```

```
gunicorn --workers 3 --timeout 300 --bind 0.0.0.0:8000 --log-file - "app:create_app()"
```

The 300-second timeout matters — the default is far shorter than a video job.

**Workers** — build, tag and push each service, then create a Container App from
the image:

```bash
docker build -t splitter-service:v1 ./splitter-service
docker tag splitter-service:v1 <registry>.azurecr.io/splitter-service:v1
docker push <registry>.azurecr.io/splitter-service:v1
```

## Repository layout

```
src/                     React UI (upload, status polling, download)
flask-backend/           Flask API bridging the UI and Azure services
splitter-service/        video to 15-second chunks
watermarker-service/     per-chunk watermarking
thumbnailer-service/     composite thumbnail from chunk keyframes
aggregator-service/      progress tracking and stage coordination
encoder-service/         chunk reassembly
queue_cleanup.py         drains the Service Bus queues between test runs
```

Each service directory holds its own `app.py` (queue listener), worker module,
`Dockerfile` and `requirements.txt`.

## Limitations

- The React frontend hardcodes the API base URL in each component rather than
  reading it from an environment variable, so pointing it at a different
  deployment means editing three files.
- Container Apps were created through the Portal and configured by hand. There
  is no infrastructure-as-code, so the deployment is not reproducible from this
  repository alone — Bicep or Terraform would fix that.
- Testing was manual uploads through the UI, not generated load, so concurrency
  was only ever tested at two simultaneous jobs.
- Thumbnails come from fixed-interval keyframes; scene-change detection would
  pick more representative frames.
- Logs are scattered across App Service, Container Apps and Service Bus with no
  correlation ID tying one job's path through the system together, which made
  debugging slower than it needed to be.

Full write-up, including the per-service algorithms and the architecture
diagram: [`report.pdf`](report.pdf).

## Contributor

- Nallathambi Vethiappan
- Luis Chial