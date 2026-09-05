
import av
import io
from PIL import Image

def generate_composite_thumbnail(chunk_paths, output_path):
    thumbnails = []
    for path in chunk_paths:
        try:
            with open(path, "rb") as f:
                container = av.open(f)
                frame = next(container.decode(video=0))
                img = frame.to_image().resize((200, 200), Image.Resampling.LANCZOS)
                thumbnails.append(img)
        except (StopIteration, av.AVError) as e:
            print(f"Skipping {path} due to error: {e}")
            continue

    if not thumbnails:
        raise ValueError("No thumbnails could be generated from the chunks.")

    total_width = 200 * len(thumbnails)
    composite = Image.new("RGB", (total_width, 200))
    for i, img in enumerate(thumbnails):
        composite.paste(img, (i * 200, 0))

    composite.save(output_path)
