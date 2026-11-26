"""Pinned local ONNX raw YOLO adapter. No downloads, depth inference or score writes."""
import hashlib
from pathlib import Path
from time import perf_counter

import numpy as np
import onnxruntime as ort
from PIL import Image

from core.vision import Detection, ModelDescriptor


def overlap(a, b):
    intersection = max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))
    return intersection / ((a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection)


class OnnxDetector:
    def __init__(self, descriptor: ModelDescriptor, root):
        self.descriptor = ModelDescriptor.model_validate(descriptor.model_dump())
        descriptor = self.descriptor
        root = Path(root).resolve()
        path = (root / descriptor.path).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Model escapes its registered root")
        with path.open("rb") as handle:
            if hashlib.file_digest(handle, "sha256").hexdigest() != descriptor.sha256:
                raise ValueError("Model checksum differs")
        if descriptor.licence_decision == "not_reviewed":
            raise ValueError("Record an offline-use licence decision before running this model")
        options = ort.SessionOptions()
        options.intra_op_num_threads = options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(path), sess_options=options, providers=[descriptor.provider])
        inputs = self.session.get_inputs()
        expected = [1, 3, descriptor.input_height, descriptor.input_width]
        if len(inputs) != 1 or inputs[0].type != "tensor(float)" or len(inputs[0].shape) != 4:
            raise ValueError("Expected one float32 NCHW input")
        if any(isinstance(actual, int) and actual != size for actual, size in zip(inputs[0].shape, expected)):
            raise ValueError("Model input shape differs from descriptor")
        if len(self.session.get_outputs()) != 1:
            raise ValueError("Expected exactly one raw detection output")
        self.input_name = inputs[0].name

    def detect(self, image):
        start = perf_counter()
        image = image.convert("RGB")
        width, height = image.size
        if not 16 <= width <= 8192 or not 16 <= height <= 8192:
            raise ValueError("Source image exceeds vision resolution bounds")
        d = self.descriptor
        scale = min(d.input_width/width, d.input_height/height)
        resized = (max(1, round(width*scale)), max(1, round(height*scale)))
        left, top = (d.input_width-resized[0])//2, (d.input_height-resized[1])//2
        canvas = Image.new("RGB", (d.input_width, d.input_height), (114, 114, 114))
        canvas.paste(image.resize(resized, Image.Resampling.BILINEAR), (left, top))
        tensor = np.asarray(canvas, dtype=np.float32).transpose(2, 0, 1)[None] / np.float32(255)
        ready = perf_counter()
        output = self.session.run(None, {self.input_name: tensor})[0]
        inferred = perf_counter()
        if (output.ndim != 3 or output.shape[:2] != (1, 4+d.class_count)
                or output.shape[2] > 100000 or not np.isfinite(output).all()):
            raise ValueError("Expected finite raw output [1,4+classes,N]; other export layouts are unsupported")
        rows = output[0].T
        if rows.size and (np.any(rows[:, 4:] < 0) or np.any(rows[:, 4:] > 1)):
            raise ValueError("Expected probability class scores, not logits/objectness")
        choices = []
        sx, sy = resized[0]/width, resized[1]/height
        for index, row in enumerate(rows):
            class_id = int(np.argmax(row[4:]))
            score = float(row[4+class_id])
            if class_id not in d.classes or score < d.min_score or row[2] <= 0 or row[3] <= 0:
                continue
            box = (max(0, min(width, (float(row[0])-float(row[2])/2-left)/sx)),
                   max(0, min(height, (float(row[1])-float(row[3])/2-top)/sy)),
                   max(0, min(width, (float(row[0])+float(row[2])/2-left)/sx)),
                   max(0, min(height, (float(row[1])+float(row[3])/2-top)/sy)))
            if box[2] > box[0] and box[3] > box[1]:
                choices.append((score, index, d.classes[class_id], box))
        choices.sort(key=lambda item: (-item[0], item[1]))
        selected = []
        for score, index, kind, box in choices[:d.pre_nms_limit]:
            if any(previous.kind == kind and overlap(box, previous.bbox) > d.nms_iou for previous in selected):
                continue
            selected.append(Detection(kind=kind, bbox=box, score=score))
            if len(selected) >= d.max_detections:
                break
        end = perf_counter()
        return selected, dict(preprocess_seconds=ready-start, inference_seconds=inferred-ready,
                             postprocess_seconds=end-inferred, total_seconds=end-start)
