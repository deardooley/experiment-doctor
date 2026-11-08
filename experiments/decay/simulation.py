"""Original forward Euler decay fixture; runs only inside an untrusted sandbox."""
import csv
import json
import sys
from pathlib import Path

p = json.loads(sys.argv[1])
t, x = 0.0, p["x0"]
with Path("/output/trajectory.csv").open("w", newline="") as stream:
    writer = csv.writer(stream)
    writer.writerow(["t", "x"])
    writer.writerow([t, x])
    while t < p["t_end"]:
        step = min(p["dt"], p["t_end"] - t)
        x -= p["k"] * x * step
        t = min(t + step, p["t_end"])
        writer.writerow([t, x])
print("simulation completed")
