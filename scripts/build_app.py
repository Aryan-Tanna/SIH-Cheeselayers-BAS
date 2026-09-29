"""Package the co-pilot (GUI) as a standalone app folder with PyInstaller.

    python scripts/build_app.py            # -> dist/BAS-Copilot/
    python scripts/build_app.py --zip      # + dist/BAS-Copilot-<os>.zip

Run it from the project venv on each target OS (PyInstaller does not
cross-compile: build the Windows app on Windows, the macOS app on a Mac,
Linux on Linux). The result needs no Python install:

    dist/BAS-Copilot/BAS-Copilot(.exe)   same options as scripts/run_gui.py
    dist/BAS-Copilot/configs/            editable (camera source, profile, ...)
    dist/BAS-Copilot/models/             detector .onnx, hand landmarker, speech + ASR
    dist/BAS-Copilot/logs, recordings/   created on first run

The detector must be an .onnx (configs/runtime.yaml detector.weights):
torch/ultralytics are left out of the app (~1 GB) and src/perception/
detector.py runs the .onnx on onnxruntime alone. Export steps for a new
model: models/README.md. Needs the `build` extra (PyInstaller) in the venv.
"""

from __future__ import annotations

import argparse
import platform
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.runtime.config import load_runtime_config  # noqa: E402

NAME = "BAS-Copilot"
# Never needed at runtime; several would pull in hundreds of MB
# (piper.train -> torch + lightning; ultralytics -> torch). matplotlib
# stays: mediapipe's tasks API imports it.
EXCLUDES = [
    "torch", "torchvision", "torchaudio", "ultralytics", "lightning",
    "pytorch_lightning", "tensorflow", "onnx", "onnxscript", "pandas",
    "polars", "scipy", "sympy", "IPython", "jupyter", "notebook", "pytest",
    "piper.train", "piper.http_server", "flask",
]
# Packages with data files / native libraries loaded at run time.
COLLECT_ALL = ["piper", "vosk", "imageio_ffmpeg", "mediapipe"]
# Only what the runtime reads; training weights (.pt) stay out.
MODEL_DIRS = ["asr", "tts"]


# Developer-only config: never shipped.
DEV_ONLY = ("configs/training/", "configs/objects/LABELLING_")


def copy_configs(dest: Path) -> None:
    """Ship ONLY config files committed in git (minus developer-only ones):
    experiments made locally in the editor, local edits to settings and
    anything else that should stay on this PC never go into the app.
    Without git (a source zip), everything under configs/ except DEV_ONLY."""
    import subprocess

    try:
        tracked = subprocess.run(["git", "ls-files", "configs"], cwd=REPO_ROOT, capture_output=True,
                                 text=True, check=True).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        tracked = [p.relative_to(REPO_ROOT).as_posix() for p in (REPO_ROOT / "configs").rglob("*") if p.is_file()]
    shipped, left_out = 0, []
    for rel in tracked:
        if rel.startswith(DEV_ONLY):
            continue
        dst = dest / Path(rel).relative_to("configs")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / rel, dst)
        shipped += 1
    local = [p.relative_to(REPO_ROOT).as_posix() for p in (REPO_ROOT / "configs").rglob("*")
             if p.is_file() and p.relative_to(REPO_ROOT).as_posix() not in tracked]
    left_out = [r for r in local if not r.startswith(DEV_ONLY)]
    # a committed file with LOCAL changes ships as committed? No: git ls-files
    # lists it, and the working copy is copied -- warn so nothing slips through.
    try:
        changed = subprocess.run(["git", "diff", "--name-only", "--", "configs"], cwd=REPO_ROOT,
                                 capture_output=True, text=True).stdout.split()
    except OSError:
        changed = []
    print(f"configs: {shipped} committed files shipped; left out (local only): {left_out or 'none'}")
    if changed:
        print(f"WARNING: these shipped configs have UNCOMMITTED local edits: {changed} -- "
              "commit or revert them if they should not be in the app")


def build(clean: bool) -> Path:
    import PyInstaller.__main__

    cfg = load_runtime_config()
    weights = Path(cfg["detector"]["weights"])
    if weights.suffix.lower() != ".onnx":
        raise SystemExit(f"detector.weights is {weights}; the app ships without torch -- "
                         f"export it to .onnx first (models/README.md)")
    hand_model = Path(((cfg.get("perception") or {}).get("hand_pose") or {}).get(
        "model", "models/hand_landmarker.task"))
    args = [
        str(REPO_ROOT / "scripts" / "run_gui.py"),
        "--name", NAME, "--onedir", "--noconfirm",
        "--paths", str(REPO_ROOT),
        "--distpath", str(REPO_ROOT / "dist"),
        # work files outside the repo: it lives in a synced OneDrive folder
        "--workpath", str(Path(tempfile.gettempdir()) / "bas_copilot_build"),
        "--specpath", str(Path(tempfile.gettempdir()) / "bas_copilot_build"),
        # console kept: startup checks, mic/camera warnings and the session
        # summary print there -- useful at a demo when something is off
        "--console",
    ]
    if clean:
        args.append("--clean")
    for m in EXCLUDES:
        args += ["--exclude-module", m]
    for m in COLLECT_ALL:
        args += ["--collect-all", m]
    PyInstaller.__main__.run(args)

    out = REPO_ROOT / "dist" / NAME
    copy_configs(out / "configs")
    (out / "models").mkdir(exist_ok=True)
    for f in (weights, hand_model):
        shutil.copy2(REPO_ROOT / f, out / f)
    for d in MODEL_DIRS:
        shutil.copytree(REPO_ROOT / "models" / d, out / "models" / d, dirs_exist_ok=True)
    (out / "README.txt").write_text(README, encoding="utf-8")
    return out


README = """BAS Co-Pilot (SIH PS 26174, team Cheeselayers)

START: double-click BAS-Copilot.exe. At the top right choose what this PC is:

  SPACE STATION  - runs the experiment: pick it, the props and the camera
                   (webcam number, "IP camera..." for a phone, or a video file),
                   optionally tick "Send to Earth" + the Earth PC's IP, Start.
  EARTH          - Mission Control: shows this PC's IP (tell the station),
                   then "Start receiving".

Two ways to report to Earth:
  LIVE      tick "Send to Earth" before starting.
  LATER     run offline; afterwards Sessions tab -> "Send to Earth".

During the experiment: Space pause, N next step, R repeat, Q quiet, H help.
Voice: "Hey BAS, next step / repeat / pause / resume / restart experiment (twice)".

Files: logs/ (hash-chained logs, reports, event photos), recordings/ (video),
ground_archive/ (what Earth received), configs/ (settings, experiments).
Windows may ask to allow the app through the firewall: allow Private networks.
Fully offline: the app refuses any connection outside the local network
except the Earth IP you type.
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", action="store_true", help="also write dist/BAS-Copilot-<os>.zip")
    ap.add_argument("--clean", action="store_true", help="clear PyInstaller's cache first")
    args = ap.parse_args()
    out = build(args.clean)
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file()) / 1e6
    print(f"\nbuilt {out} ({size:.0f} MB)")
    if args.zip:
        z = shutil.make_archive(str(out.parent / f"{NAME}-{platform.system().lower()}"), "zip",
                                out.parent, NAME)
        print(f"zipped {z} ({Path(z).stat().st_size / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
