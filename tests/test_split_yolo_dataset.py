import csv

import pytest

from scripts.split_yolo_dataset import split


def _make_dataset(dataset_dir, frames):
    """frames: list of (clip_id, frame_idx, class_id_or_None)"""
    images_train = dataset_dir / "images" / "train"
    labels_train = dataset_dir / "labels" / "train"
    images_train.mkdir(parents=True)
    labels_train.mkdir(parents=True)
    for clip_id, idx, cls in frames:
        stem = f"{clip_id}_{idx:06d}"
        (images_train / f"{stem}.jpg").write_bytes(b"fake")
        line = f"{cls} 0.1 0.1 0.2 0.1 0.2 0.2 0.1 0.2\n" if cls is not None else ""
        (labels_train / f"{stem}.txt").write_text(line, encoding="utf-8")


def _make_manifest(path, clip_sessions):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["clip_id", "session_id"])
        writer.writeheader()
        for clip_id, session_id in clip_sessions.items():
            writer.writerow({"clip_id": clip_id, "session_id": session_id})


def test_frames_route_to_val_by_session(tmp_path):
    dataset_dir = tmp_path / "yolo_dataset"
    _make_dataset(dataset_dir, [
        ("Dataset10_glovebox", 0, 0),
        ("Dataset10_glovebox", 1, 2),
        ("Dataset20_glovebox", 0, 6),
    ])
    manifest = tmp_path / "clips.csv"
    _make_manifest(manifest, {"Dataset10_glovebox": "S00", "Dataset20_glovebox": "S01"})

    summary = split(dataset_dir, manifest, val_sessions={"S01"})

    assert summary["moved_to_val"] == 1
    assert summary["kept_in_train"] == 2
    train_imgs = {p.name for p in (dataset_dir / "images" / "train").glob("*.jpg")}
    val_imgs = {p.name for p in (dataset_dir / "images" / "val").glob("*.jpg")}
    assert val_imgs == {"Dataset20_glovebox_000000.jpg"}
    assert train_imgs == {"Dataset10_glovebox_000000.jpg", "Dataset10_glovebox_000001.jpg"}
    # label moved alongside its image
    assert (dataset_dir / "labels" / "val" / "Dataset20_glovebox_000000.txt").exists()
    assert not (dataset_dir / "labels" / "train" / "Dataset20_glovebox_000000.txt").exists()


def test_unknown_session_refuses_not_guesses(tmp_path):
    dataset_dir = tmp_path / "yolo_dataset"
    _make_dataset(dataset_dir, [("DatasetX_glovebox", 0, 0)])
    manifest = tmp_path / "clips.csv"
    _make_manifest(manifest, {})  # DatasetX not in manifest at all

    with pytest.raises(SystemExit):
        split(dataset_dir, manifest, val_sessions={"S01"})


def test_val_rebuilt_clean_each_run(tmp_path):
    """A stale val/ from a previous split call must not linger."""
    dataset_dir = tmp_path / "yolo_dataset"
    _make_dataset(dataset_dir, [("Dataset10_glovebox", 0, 0)])
    manifest = tmp_path / "clips.csv"
    _make_manifest(manifest, {"Dataset10_glovebox": "S00"})

    # First split: nothing held out.
    split(dataset_dir, manifest, val_sessions=set())
    assert list((dataset_dir / "images" / "val").glob("*.jpg")) == []

    # Manually drop a stale file into val to simulate leftover state.
    stale = dataset_dir / "images" / "val" / "stale.jpg"
    stale.write_bytes(b"stale")
    assert stale.exists()

    # Re-split with the same (now train-only) pool -- val must come
    # back empty again, not keep the stale file.
    split(dataset_dir, manifest, val_sessions=set())
    assert list((dataset_dir / "images" / "val").glob("*.jpg")) == []
