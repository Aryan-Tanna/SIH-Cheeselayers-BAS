#!/usr/bin/env python3
"""Train/fine-tune a YOLOv8-OBB detector. Wraps the two environment
workarounds documented in pyproject.toml (numpy.trapz removed under
numpy 2.x; keep opencv-contrib-python, not opencv-python) so every
training invocation doesn't have to remember them by hand.

CPU only (this project's edge target), so pick --epochs with the
background-shell memory-pressure reaper in mind: a long run has more
exposure to getting killed mid-training. Checkpointing is per-epoch
either way, so a kill is recoverable with --resume, not a data loss
event -- see CLAUDE.md's session-status gotchas.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", type=Path, default=None,
                     help="Base checkpoint to start from, e.g. yolov8n-obb.pt for "
                          "from-scratch, or a prior run's best.pt to fine-tune from. "
                          "Not needed with --resume (loads --name's own last.pt).")
    ap.add_argument("--data", type=Path, default=Path("runs/yolo_dataset/data.yaml"))
    ap.add_argument("--epochs", type=int, default=50)
    ap.add_argument("--patience", type=int, default=20)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--name", required=True, help="Run name under runs/train/<name>/")
    ap.add_argument("--workers", type=int, default=0,
                     help="Dataloader worker processes. 0 keeps memory footprint down "
                          "-- see the background-kill history in CLAUDE.md.")
    ap.add_argument("--resume", action="store_true",
                     help="Resume an interrupted run at --name from its last.pt, "
                          "ignoring the other training args (Ultralytics reuses the "
                          "original run's saved args.yaml).")
    ap.add_argument("--augment-config", type=Path, default=None,
                     help="YAML with 'ultralytics' (train() augmentation hyps) and "
                          "'photometric' (scripts/photometric_aug.py) sections, e.g. "
                          "configs/training/augment_v4.yaml. Augmentation is on-the-fly; "
                          "nothing is written to disk. Omit for Ultralytics defaults.")
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--device", default="cpu",
                     help="'cpu' (default) or a CUDA index like '0'. GPU is for training "
                          "only -- needs the CUDA torch in .venv-train; the runtime stays CPU.")
    args = ap.parse_args()

    import numpy
    numpy.trapz = numpy.trapezoid  # ultralytics 8.3.28 calls the numpy<2 API
    from ultralytics import YOLO

    aug_hyps: dict = {}
    if args.augment_config is not None:
        import yaml
        import photometric_aug
        aug = yaml.safe_load(args.augment_config.read_text(encoding="utf-8"))
        aug_hyps = aug.get("ultralytics", {})
        # Must be installed before train() builds the dataset -- and on
        # --resume too, since the hook is process state, not saved args.
        photometric_aug.install(aug.get("photometric", {}))
        print(f"augment config : {args.augment_config}")
        print(f"  ultralytics  : {aug_hyps}")
        print(f"  photometric  : {sorted(aug.get('photometric', {}))}")

    if args.resume:
        weights = Path("runs/train") / args.name / "weights" / "last.pt"
        if not weights.exists():
            raise SystemExit(f"--resume given but {weights} doesn't exist -- nothing to resume")
        model = YOLO(str(weights))
        model.train(resume=True)
        return 0

    if args.weights is None:
        raise SystemExit("--weights is required unless --resume is given")

    if not args.data.exists():
        raise SystemExit(f"{args.data} doesn't exist -- run convert_labels_to_yolo_obb.py "
                          f"(and split_yolo_dataset.py, if you want a real val split) first")

    model = YOLO(str(args.weights))
    model.train(
        data=str(args.data), epochs=args.epochs, patience=args.patience,
        imgsz=args.imgsz, device=args.device, workers=args.workers, batch=args.batch,
        project="runs/train", name=args.name, exist_ok=True, **aug_hyps,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
