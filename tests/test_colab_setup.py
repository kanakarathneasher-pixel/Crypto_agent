import hashlib
import json
import sys
from types import SimpleNamespace
import zipfile

import pytest
from scripts import prepare_colab
from src import tensorflow_research as research


def test_gpu_mode_rejects_unavailable_gpu(monkeypatch):
    monkeypatch.setattr(research, "DEVICE_MODE", "gpu")
    monkeypatch.setitem(sys.modules, "tensorflow", SimpleNamespace(
        config=SimpleNamespace(list_physical_devices=lambda kind: [])))
    with pytest.raises(RuntimeError, match="GPU requested"):
        research.tensorflow()


def test_bundle_allowlist_and_notebook_training_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(prepare_colab, "ROOT", tmp_path)
    for name in prepare_colab.FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture")
    (tmp_path / ".env").write_text("SECRET=not-for-upload")
    archive, notebook = prepare_colab.build()
    with zipfile.ZipFile(archive) as bundle:
        assert set(bundle.namelist()) == set(prepare_colab.FILES) | {"manifest.json"}
        manifest = json.loads(bundle.read("manifest.json"))
        assert all(hashlib.sha256(bundle.read(n)).hexdigest() == v for n, v in manifest.items())
    contents = json.loads(notebook.read_text())
    for cell in contents["cells"]:
        if cell["cell_type"] == "code":
            compile("".join(cell["source"]), "cell", "exec")
    training = [cell for cell in contents["cells"] if
                cell["cell_type"] == "code" and "research.train(" in "".join(cell["source"])]
    assert len(training) == 1
    assert "START_TRAINING = False" in "".join(training[0]["source"])
