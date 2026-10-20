"""Write the exact successful isolated environment, without changing backend pins."""
from pathlib import Path
import subprocess
import sys

if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, "-m", "pip", "freeze"], check=True, capture_output=True, text=True)
    header = "# Tested isolated TensorFlow research environment: Windows x64, Python 3.11.\n"
    (root / "requirements-tensorflow.txt").write_text(header + result.stdout, encoding="utf-8")
    print("Saved requirements-tensorflow.txt")
