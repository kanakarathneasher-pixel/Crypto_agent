# Colab GPU training through VS Code

Open `notebooks/coinbase_colab.ipynb`. Select Kernel → Colab → New Colab
Server and choose an available GPU. Complete Google's sign-in yourself.
See the [official extension guide](https://github.com/googlecolab/colab-vscode/wiki/User-Guide).

The generated bundle is `data/processed/colab/crypto_agent_colab.zip`.
Right-click that file in VS Code Explorer and select **Upload to Colab**.
It should appear at `/content/crypto_agent_colab.zip`.
The checked-in notebook uses runtime storage because Drive authorization failed
during the completed experiment. Upload the ZIP to the runtime directly.

Run notebook cells in order.
Setup checks bundle hashes, retains Colab's installed TensorFlow/CUDA stack,
checks for an actual GPU and prepares chronological splits with training-only
scalers. Helper dependency installation may require restarting the kernel if
packages were already imported; rerun setup after a restart.

The training cell has `START_TRAINING = False`. Review the preparation output,
then change this to `True` and run that cell to start. No live trading code is
included. Local Windows training continues to default to CPU.

The checked-in notebook saves results and checkpoints under
`/content/research_models/tensorflow-<timestamp>/`. The final cell creates a ZIP;
download it through Colab Contents before disconnecting. Runtime files are temporary.
Automatic epoch/optimizer resume is not implemented. Each training call creates
a separate version. The completed run's downloaded artifacts are preserved locally
under `models/tensorflow-20261022T052236408074Z/` and excluded from Git.

Only public candles, three research source files and the prior split metadata
are bundled. No credentials, account database, backend, model binaries or virtual
environment are uploaded. The bundle is ignored by Git.

To regenerate the bundle and a fresh notebook after changing source or data:

```powershell
.\.venv\Scripts\python.exe scripts/prepare_colab.py
```

The generator currently creates the optional Drive-based workflow and replaces
the notebook, including its saved output. Preserve the completed notebook first.
The checked-in notebook contains the actual completed GPU training output.
See `docs/tensorflow_results.md` for measured results.
No fresh final-test claim can be made from these historical development folds.
