# TensorFlow sequence-model experiment

This experiment uses a separate **`.venv-tf`** environment. The backend's Python 3.14 `.venv`, its requirements, original Binance scripts/model and Coinbase data files remain unchanged. Native Windows CPU TensorFlow uses the already installed Python 3.11. No CUDA, WSL or system Python installation is required for this CPU experiment. See the [official installation guide](https://www.tensorflow.org/install/pip).

## Reproduce the environment

From the project root in PowerShell:

```powershell
py -3.11 -m venv .venv-tf
.\.venv-tf\Scripts\python.exe -m pip install --upgrade pip
.\.venv-tf\Scripts\python.exe -m pip install -r requirements-tensorflow.in
.\.venv-tf\Scripts\python.exe -m pip check
```

The `.in` file records allowed dependencies. After verifying installation, run `scripts/freeze_tensorflow_environment.py` with `.venv-tf` to generate a `.txt` snapshot of installed versions. The application continues to run with `.venv`; use `.venv-tf` explicitly for these commands. Don't install the backend's Python 3.14-specific package pins in the Python 3.11 research environment.

## Train

First prepare and inspect the data splits without training:

```powershell
.\.venv-tf\Scripts\python.exe -m src.tensorflow_research prepare
```

This validates input sequences and saves training-only scalers and
`data/processed/tensorflow_preparation/preparation_report.json`. It constructs
the networks to check their architecture but does not fit them to market data.

After reviewing the report, start training explicitly:

```powershell
.\.venv-tf\Scripts\python.exe -m src.tensorflow_research train
```

By default this trains 48-hour sequence models, at most 25 epochs per fit, with early stopping. It compares small **GRU and LSTM** networks, XGBoost (depth 2/3 chosen on validation only), zero-return and last-hour-return persistence baselines. Each network uses 32 recurrent units, dropout, a small dense layer, L2 regularization, MAE loss and gradient clipping. Checkpoints save the minimum validation-loss model; later evaluation uses that exact saved model. The architecture uses the official [Keras GRU](https://keras.io/api/layers/recurrent_layers/gru/) and [EarlyStopping](https://keras.io/api/callbacks/early_stopping/) APIs.

The 19 original technical features become 21 sequence inputs: price-level indicators are divided by the current completed close, RSI is scaled, and hour/weekday use sine/cosine encodings. Returns/volatility stay in fractional units. A scaler fits only unique observations in training windows; scaled features are clipped at +/-10 training standard deviations. The target is multiplied by 100 during training for numerical convenience and divided by 100 for every forecast and metric.

Inputs use only completed candles up to t. The label is `close[t+1]/close[t]-1`. Indicators restart at gaps, and neither input sequences nor labels cross missing hours. A single observation is purged at each label boundary. Validation/evaluation input windows may use earlier training candles as context because those candles are already known at forecast time.

## Evaluation boundaries

The prior model's **original validation and final-test periods are excluded before feature engineering**. Only raw candles up to the original training target cutoff (2025-10-23 10:00 UTC) are used. Two expanding chronological development folds are defined in advance:

| Fold | Fit window | Early stopping / selection | Development evaluation |
| --- | --- | --- | --- |
| 1 | First 50% of eligible sequences | 50–65% | 65–80% |
| 2 | First 70% | 70–85% | 85–100% |

Each fold freezes its own selection before its own evaluation. Pooled metrics for the selected model use each fold's own validation-selected winner; there is no retrospective selection using later evaluation results. The saved root `model.keras` is the **latest fold's best neural model by validation MAE**, even if XGBoost wins that fold overall. There is no refit on evaluation labels.

These are development comparisons inside dates used in earlier research, **not a new untouched final test**. They cannot demonstrate a reliable 90% accuracy or qualify a model for production. A new future holdout and a separate cost-aware strategy evaluation are still required. The report always records `eligible=false`, `approved=false`. No trading setting or approved-model pointer is changed. The existing production loader rejects this different sequence schema.

## Saved artifacts

Each run creates a unique `models/tensorflow-TIMESTAMP/` directory containing:

- `model.keras`, the latest-fold selected neural checkpoint.
- `scaler.joblib`, exact feature order, lookback, target scale and preprocessing schema in `metadata.json`.
- Separate GRU/LSTM models, training CSV logs, tuned XGBoost and metrics for each fold.
- Timestamped development predictions, pooled scores, date boundaries, package/device details, input data/reference hashes and artifact checksums.

MAE/RMSE measure return errors. Directional accuracy includes only actual absolute returns above one basis point; a zero prediction counts as a miss. The count and coverage of predictions above 2% are shown separately. High accuracy on a tiny selected subset must never be presented as accuracy on all hours. Forecast magnitudes are not calibrated probabilities.

## Research inference and tests

Use the actual printed output directory. For a reproducible historical example ending at the original development cutoff:

```powershell
.\.venv-tf\Scripts\python.exe -m src.tensorflow_research predict --directory models/YOUR_TENSORFLOW_VERSION --as-of 2025-10-23T11:00:00+00:00
.\.venv-tf\Scripts\python.exe -m pytest tests/test_neural_data.py tests/test_tensorflow_research.py -q
```

Inference validates schema, artifact checksums, exact model shape, data freshness and contiguous completed inputs, then reports a diagnostic return/price estimate with `validated=false`. A clipped-input fraction warns about distribution shift. It has no execution or promotion capability. Joblib artifacts must be trusted local files.

The normal application suite remains:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

TensorFlow-specific tests skip in the normal environment where TensorFlow is intentionally absent. Do not rerun many configurations based on development evaluation scores and then label the best score an independent test result. Record new experiments and obtain new future data for final assessment.
