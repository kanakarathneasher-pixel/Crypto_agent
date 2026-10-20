"""Run weekly/monthly with Windows Task Scheduler; never promotes a model."""
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from backend.worker import WorkerLock

if __name__ == '__main__':
    lock = WorkerLock(root / '.worker-retraining.lock')
    if not lock.acquire():
        raise SystemExit('A retraining/download workflow is already active.')
    try:
        subprocess.run([sys.executable, 'src/coinbase_data_loader.py'], cwd=root, check=True)
        subprocess.run([sys.executable, '-m', 'src.research', 'train'], cwd=root, check=True)
        print('Candidate evaluation finished. Review metadata against the current approved model before explicit promotion.')
    finally:
        lock.close()
