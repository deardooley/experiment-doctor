"""Repository-owned probe sources. These strings execute ONLY inside sandboxes."""
import json


def network_source(host, port, marker):
    targets = [("host_listener", host, port), ("external", "1.1.1.1", 443)]
    return '''import json, socket
results = []
for label, host, port in json.loads(%r):
    try:
        stream = socket.create_connection((host, port), timeout=1)
    except OSError as exc:
        results.append({"target": label, "connected": False, "errno": exc.errno})
    else:
        # A later send failure must never conceal a successful connection.
        with stream:
            try:
                stream.sendall(%r)
            except OSError:
                pass
        results.append({"target": label, "connected": True, "errno": None})
print(json.dumps({"connections": results}), flush=True)
''' % (json.dumps(targets), marker.encode())


def canary_source(host_path, previous_artifact_path, marker_name="EXPERIMENT_DOCTOR_TEST_SECRET"):
    return '''import json, os
from pathlib import Path
result = {}
for label, path in json.loads(%r):
    try:
        raw = Path(path).read_text()
        result[label] = {"denied": False, "contents": raw}
    except OSError as exc:
        result[label] = {"denied": True, "errno": exc.errno}
result["environment_marker_absent"] = %r not in os.environ
result["fresh_output"] = not Path("/output/trajectory.csv").exists()
result["runtime_socket_absent"] = not Path("/var/run/docker.sock").exists()
try:
    Path("/ed-readonly-probe").write_text("controlled write")
    result["readonly_root"] = {"denied": False}
except OSError as exc:
    result["readonly_root"] = {"denied": True, "errno": exc.errno}
Path("/output/trajectory.csv").write_text("t,x\\n0,1\\n5,0\\n")
result["tmpfs_writable"] = True
print(json.dumps(result), flush=True)
''' % (json.dumps([("host_canary", str(host_path)), ("cross_job_artifact", str(previous_artifact_path))]), marker_name)


SYMLINK = "from pathlib import Path\nPath('/output/trajectory.csv').symlink_to('/etc/passwd')\n"
# Hard-link within output stays on the same tmpfs and must be rejected even if the
# link count changes between enumeration and opening.
HARDLINK = "import os\nfrom pathlib import Path\np=Path('/output/trajectory.csv'); p.write_text('bad'); os.link(p,'/output/alias')\n"
FIFO = "import os\nos.mkfifo('/output/trajectory.csv')\n"
OVERSIZED = "from pathlib import Path\nPath('/output/trajectory.csv').write_bytes(b'x' * (10*1024*1024))\n"
ACTIVE_MARKUP = "from pathlib import Path\nPath('/output/attack.svg').write_text('<svg onload=alert(1)></svg>')\n"
LOG_FLOOD = "import sys\nsys.stdout.write('X' * (2*1024*1024)); sys.stdout.flush()\n"

MEMORY_PRESSURE = "x = bytearray(700 * 1024 * 1024)\n"
PID_PRESSURE = '''import errno, json, subprocess, sys
children = []
try:
    for _ in range(80):
        try:
            children.append(subprocess.Popen([sys.executable,'-I','-c','import time; time.sleep(10)']))
        except OSError as exc:
            assert exc.errno == errno.EAGAIN
            break
    else:
        raise AssertionError('PID cap absent')
    print(json.dumps({'pid_enforced': True, 'children': len(children)}), flush=True)
finally:
    for child in children: child.terminate()
    for child in children: child.wait()
'''
CPU_PRESSURE = '''import json, time
end = time.monotonic() + 3
while time.monotonic() < end: pass
print(json.dumps({'bounded_cpu_probe_finished': True}), flush=True)
'''
