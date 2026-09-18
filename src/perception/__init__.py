# Deliberately empty. Detector/landmark implementations land in phase 2.
# NEVER import ultralytics/mediapipe/opencv at module level anywhere in
# this package — harness/replay.py --stub-detector must run with none of
# those installed, on a clean `pip install -e .` (no [vision] extra).
# Import them lazily, inside the function that needs them, behind the
# stub-detector boundary.
