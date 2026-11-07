"""
Turn a page upright before it is read (research/0004).

Phones pointed down at a flat page often save the wrong orientation, so EXIF cannot be
relied on, and a page read upside down lost a sentence in testing. A small local classifier
sorts the page into four orientations. It does not fix skew: a tilted page stays tilted.

onnxruntime and the model are loaded on the first photo, not on import, because they cost
about 80 MB of memory and 1.6 s and a process may never read a photo.
"""

import logging
import threading
from importlib.resources import files
from typing import TYPE_CHECKING

from PIL import Image

if TYPE_CHECKING:
    import numpy as np
    from onnxruntime import InferenceSession

logger = logging.getLogger(__name__)

MODEL_FILE = "models/PP-LCNet_x1_0_doc_ori.onnx"
# How far the page sits clockwise, in the order the model scores them.
LABELS = (0, 90, 180, 270)
# Every page with text scored at least this, and a blank page scored 0.32. The model's
# confidence tops out near 0.93, so a threshold of 0.95 would never turn anything.
MIN_CONFIDENCE = 0.5

# The model's own recipe (its inference.yml): the centre 224 of a page scaled to 256 on
# its short side, then ImageNet scaling.
INPUT_PX = 224
SCALED_SHORT_SIDE_PX = 256
MEAN = (0.485, 0.456, 0.406)
STD = (0.229, 0.224, 0.225)

_lock = threading.Lock()
_session: "InferenceSession | None" = None


def _classifier() -> "InferenceSession":
    """The one shared session; a consumer's threads may all ask for it at once."""
    global _session
    with _lock:
        if _session is None:
            import onnxruntime

            options = onnxruntime.SessionOptions()
            # About 14 ms on one thread is plenty, and a container can report far more
            # processors than it is allowed to use.
            options.intra_op_num_threads = 1
            options.inter_op_num_threads = 1
            # The exported model carries unused values, and ONNX Runtime warns about each
            # one to stderr on every load. Errors still print.
            options.log_severity_level = 3
            _session = onnxruntime.InferenceSession(
                files("photo_ocr").joinpath(MODEL_FILE).read_bytes(),
                options,
                providers=["CPUExecutionProvider"],
            )
        return _session


def _pixels(image: Image.Image) -> "np.ndarray":
    """
    The model's input, following the measured recipe exactly. A strip longer than twice
    its width is cut down first, because scaling one whole would need hundreds of MB and
    only its centre is used. Ordinary pages are not affected by that cut.
    """
    import numpy as np

    short = min(image.size)
    width, height = min(image.width, 2 * short), min(image.height, 2 * short)
    left, top = (image.width - width) // 2, (image.height - height) // 2
    scale = SCALED_SHORT_SIDE_PX / short
    scaled_page = image.crop((left, top, left + width, top + height)).resize(
        (round(width * scale), round(height * scale)), Image.Resampling.BILINEAR
    )
    left, top = (scaled_page.width - INPUT_PX) // 2, (scaled_page.height - INPUT_PX) // 2
    crop = scaled_page.crop((left, top, left + INPUT_PX, top + INPUT_PX))
    scaled = np.asarray(crop, dtype=np.float32) / 255
    normal = (scaled - np.array(MEAN, dtype=np.float32)) / np.array(STD, dtype=np.float32)
    return normal.transpose(2, 0, 1)[None]


def classify(image: Image.Image) -> tuple[int, float]:
    """How far an RGB page sits clockwise, and the model's confidence in that."""
    session = _classifier()
    scores = session.run(None, {session.get_inputs()[0].name: _pixels(image)})[0][0]
    best = int(scores.argmax())
    return LABELS[best], float(scores[best])


def turn_upright(image: Image.Image) -> Image.Image:
    """The RGB page turned upright, or unchanged when the classifier is not confident."""
    label, confidence = classify(image)
    if label == 0 or confidence < MIN_CONFIDENCE:
        return image
    logger.info("Turning a page by %s degrees, at confidence %.2f", label, confidence)
    # PIL turns counter-clockwise, which undoes a label measured clockwise.
    return image.rotate(label, expand=True)
