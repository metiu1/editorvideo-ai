import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from vedit import ffmpeg  # noqa: E402


def _gen(path: Path, args: list[str]) -> str:
    if path.exists():
        return str(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([ffmpeg.binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", *args, str(path)],
                   check=True, capture_output=True)
    return str(path)


@pytest.fixture
def anyio_backend():
    """Un solo backend: il server gira su asyncio."""
    return "asyncio"


@pytest.fixture(scope="session")
def assets(tmp_path_factory) -> dict:
    """Sorgenti sintetiche: niente file esterni, il test gira ovunque."""
    d = tmp_path_factory.mktemp("assets")
    return {
        "red": _gen(d / "red.mp4", [
            "-f", "lavfi", "-i", "color=c=red:s=640x360:r=25:d=5",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=5",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
        ]),
        "blue": _gen(d / "blue.mp4", [
            "-f", "lavfi", "-i", "testsrc2=s=640x360:r=25:d=4",
            "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000:duration=4",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
        ]),
        "music": _gen(d / "music.m4a", [
            "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000:duration=8",
            "-c:a", "aac", "-b:a", "128k",
        ]),
        "logo": _gen(d / "logo.png", [
            "-f", "lavfi", "-i", "color=c=yellow:s=200x120:d=1", "-frames:v", "1",
        ]),
        "green": _gen(d / "green.mp4", [
            "-f", "lavfi", "-i", "color=c=green:s=640x360:r=25:d=3",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        ]),
    }
