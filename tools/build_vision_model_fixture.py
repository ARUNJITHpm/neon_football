"""Create a tiny constant ONNX adapter test, NOT a trained football detector."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.vision import ModelDescriptor


def varint(value):
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    return bytes(result) + bytes([value])


def integer(field, value):
    return varint(field << 3) + varint(value)


def blob(field, value):
    if isinstance(value, str):
        value = value.encode()
    return varint((field << 3) | 2) + varint(len(value)) + value


def value_info(name, shape):
    dimensions = b"".join(blob(1, integer(1, d)) for d in shape)
    tensor_type = integer(1, 1) + blob(2, dimensions)
    return blob(1, name) + blob(2, blob(1, tensor_type))


def build(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    # ONNX protobuf, IR 8 / opset 13: one Constant node, unused float input.
    # Channel order: cx,cy,w,h,person score,ball score. Third box duplicates the ball.
    values = [8, 24, 8.3, 16, 16, 16.2, 6, 8, 6, 6, 12, 6, .05, .90, .05, .95, .05, .80]
    tensor = b"".join(integer(1, v) for v in (1, 6, 3)) + integer(2, 1) + blob(9, struct.pack("<18f", *values))
    attribute = blob(1, "value") + blob(5, tensor) + integer(20, 4)
    node = blob(2, "detections") + blob(4, "Constant") + blob(5, attribute)
    graph = blob(1, node) + blob(2, "synthetic_adapter_test")
    graph += blob(11, value_info("images", [1, 3, 32, 32])) + blob(12, value_info("detections", [1, 6, 3]))
    model = integer(1, 8) + blob(2, "neon-synthetic-fixture") + blob(7, graph) + blob(8, integer(2, 13))
    (root / "constant.onnx").write_bytes(model)
    descriptor = ModelDescriptor(version="constant-adapter-test-v1", path="constant.onnx",
        sha256=hashlib.sha256(model).hexdigest(), source="Hand-authored Constant graph; input pixels are ignored",
        licence="Project-generated synthetic test fixture", licence_decision="synthetic_fixture",
        purpose="synthetic_adapter_test", input_width=32, input_height=32, class_count=2, classes={0: "player", 1: "ball"})
    (root / "model.json").write_text(json.dumps(descriptor.model_dump(mode="json"), indent=2, sort_keys=True)+"\n", encoding="utf-8")
    return descriptor


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    build(args.root)
    print("Created constant adapter fixture; no trained detector or accuracy claim")
