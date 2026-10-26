"""Black-box validation: run any load model's .dyr record (and its DLLs) through
PSS/E on a one-bus playback rig and characterize what it does as a whole.

See docs/black_box/BLACK_BOX_VALIDATION.md. Nothing here imports psspy: PSS/E runs
in its own Python, through src/psse_worker/psse_worker.py.
"""
