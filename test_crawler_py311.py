from pathlib import Path
import subprocess
import sys

py = sys.executable
script = str(Path(__file__).resolve().parent / "actions" / "moi_research.py")

print("Testing crawler...")
print(f"Command: {py} {script} --scheduled")
print("=" * 60)

result = subprocess.run(
    [py, script, "--scheduled"],
    capture_output=True,
    text=True,
    timeout=120,
    cwd=str(Path(__file__).resolve().parent)
)

print("STDOUT:", result.stdout[:3000] if result.stdout else "(empty)")
print("STDERR:", result.stderr[:2000] if result.stderr else "(empty)")
print("Return code:", result.returncode)
