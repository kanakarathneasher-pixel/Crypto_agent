"""Build a minimal research bundle and a VS Code/Colab notebook, without training."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = "models/coinbase-20261020T121949544468Z/metadata.json"
FILES = [
    "src/coinbase_pipeline.py", "src/neural_data.py", "src/tensorflow_research.py",
    "data/raw/coinbase_xrp_usdc_1h.csv", REFERENCE,
]


def build():
    destination = ROOT / "data/processed/colab"
    destination.mkdir(parents=True, exist_ok=True)
    manifest = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in FILES}
    archive = destination / "crypto_agent_colab.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name in FILES:
            bundle.write(ROOT / name, name)
        bundle.writestr("manifest.json", json.dumps(manifest, indent=2))

    cells = []
    def markdown(text):
        cells.append({"cell_type": "markdown", "metadata": {}, "source": text.splitlines(True)})
    def code(text):
        cells.append({"cell_type": "code", "metadata": {}, "execution_count": None,
                      "outputs": [], "source": text.splitlines(True)})

    markdown("""# XRP/USDC — Colab GPU research
Open this notebook in VS Code. Select Kernel → Colab, sign in, and select a GPU server.
Right-click `data/processed/colab/crypto_agent_colab.zip` in VS Code and select
**Upload to Colab**. Alternatively upload it to **My Drive/Crypto_agent/**.
Run setup cells in order. The training cell defaults to disabled, even with Run All.
Only public candles, research source, and split metadata are in the bundle.
These are development experiments, not a fresh final test or an approved trading model.
""")
    code("""from google.colab import drive
drive.mount('/content/drive')
""")
    code("""from pathlib import Path
import hashlib, json, os, sys, zipfile, tempfile, subprocess, shutil

archive = Path('/content/drive/MyDrive/Crypto_agent/crypto_agent_colab.zip')
uploaded = Path('/content/crypto_agent_colab.zip')
if uploaded.is_file():
    archive.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(uploaded, archive)
if not archive.is_file():
    raise FileNotFoundError('Use Upload to Colab for the ZIP or place it in My Drive/Crypto_agent.')
work = Path(tempfile.mkdtemp(prefix='crypto_agent_', dir='/content'))
with zipfile.ZipFile(archive) as bundle:
    manifest = json.loads(bundle.read('manifest.json'))
    if set(bundle.namelist()) != set(manifest) | {'manifest.json'}:
        raise ValueError('Unexpected bundle contents.')
    for name, expected in manifest.items():
        target = (work / name).resolve()
        if not target.is_relative_to(work.resolve()):
            raise ValueError('Unsafe archive path.')
        content = bundle.read(name)
        if hashlib.sha256(content).hexdigest() != expected:
            raise ValueError(f'Checksum mismatch: {name}')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
os.chdir(work)
sys.path.insert(0, str(work))
print('Verified and extracted research bundle:', work)
""")
    code("""# Keep Colab's supplied TensorFlow/CUDA stack; install only research helpers.
subprocess.run([sys.executable, '-m', 'pip', 'install',
                'pandas>=2.2,<4', 'scikit-learn>=1.5,<2',
                'xgboost>=2,<4', 'joblib>=1.3,<2'], check=True)
# Set device mode before importing the research module or initializing TensorFlow.
os.environ['CRYPTO_TF_DEVICE'] = 'gpu'
os.environ.pop('CUDA_VISIBLE_DEVICES', None)
os.environ['TF_DETERMINISTIC_OPS'] = '1'
import tensorflow as tf
gpus = tf.config.list_physical_devices('GPU')
if not gpus:
    raise RuntimeError('No GPU detected. Select a GPU Colab server and restart this notebook.')
for gpu in gpus:
    tf.config.experimental.set_memory_growth(gpu, True)
print('TensorFlow:', tf.__version__, 'GPUs:', gpus)
""")
    code(f"""from src import tensorflow_research as research
reference = Path({REFERENCE!r})
output_root = Path('/content/drive/MyDrive/Crypto_agent/research_models')
output_root.mkdir(parents=True, exist_ok=True)
probe = output_root / '.write_check'
probe.write_text('ok')
probe.unlink()
os.environ['CRYPTO_RESEARCH_OUTPUT'] = str(output_root)
plan = research.prepare(reference, lookback=48, epochs=25)
(output_root / 'preparation_report.json').write_text(json.dumps(plan, indent=2))
print('Ready for review. No market-data training has started.')
""")
    markdown("""## Start training only after reviewing the preparation report
Change `START_TRAINING` to `True` only when ready, then run the next cell.
Models, best-epoch checkpoints and logs save directly to Google Drive.
If a runtime disconnects, saved checkpoints remain, but automatic optimizer/epoch resume
is not implemented. A new training call creates a separate run; it does not overwrite the old one.
Do not repeatedly adjust settings based on development evaluation results.
""")
    code("""START_TRAINING = False
if START_TRAINING:
    run_directory = research.train(reference, lookback=48, epochs=25)
    print('Saved results:', run_directory)
else:
    print('Training is disabled. Review the plan before setting START_TRAINING=True.')
""")
    code("""# Display results only if this notebook completed a training run.
if 'run_directory' in globals():
    metadata = json.loads((run_directory / 'metadata.json').read_text())
    import pandas as pd
    display(pd.DataFrame(metadata['pooled_development']).T)
    print('Research only; no model promotion or trading.')
else:
    print('No completed training run in this session.')
""")
    notebook = {"cells": cells, "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python"}, "accelerator": "GPU"},
        "nbformat": 4, "nbformat_minor": 5}
    for index, cell in enumerate(cells):
        cell["id"] = f"crypto-colab-{index}"
        if cell["cell_type"] == "code":
            compile("".join(cell["source"]), f"cell-{index}", "exec")
    path = ROOT / "notebooks/coinbase_colab.ipynb"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(notebook, indent=2), encoding="utf-8")
    print(f"Notebook: {path}\nBundle: {archive}\nBundle files: {len(FILES)}")
    print("No credentials, database, virtual environment or model binaries included.")
    return archive, path


if __name__ == "__main__":
    build()
