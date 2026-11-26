"""Create a small generated MP4 pattern for authenticated dummy review, not football footage."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination",type=Path)
    args=parser.parse_args()
    executable=shutil.which("ffmpeg") or r"C:\ffmpeg\ffmpeg-master-latest-win64-gpl-shared\bin\ffmpeg.exe"
    args.destination.parent.mkdir(parents=True,exist_ok=True)
    subprocess.run([executable,"-hide_banner","-loglevel","error","-n","-f","lavfi","-i",
        "testsrc2=duration=2:size=640x360:rate=15","-an","-c:v","libx264","-preset","fast","-crf","28",
        "-pix_fmt","yuv420p","-movflags","+faststart",str(args.destination)],check=True,timeout=30)
    raw=args.destination.read_bytes()
    version=subprocess.run([executable,"-version"],capture_output=True,text=True,check=True).stdout.splitlines()[0]
    metadata=dict(kind="generated_pattern",media_id="dummy-review-pattern-v1",bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),generator=version,duration_seconds=2,width=640,height=360,rate_hz=15,
        represents_football=False,source="FFmpeg testsrc2 numeric video generator")
    args.destination.with_suffix(".json").write_text(json.dumps(metadata,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(metadata))
