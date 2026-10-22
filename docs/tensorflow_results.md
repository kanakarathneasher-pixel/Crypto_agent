# TensorFlow development results

Run: `tensorflow-20261022T052236408074Z`. Completed on Colab GPU.

These are historical development evaluations, not a fresh final test.
Both neural networks failed to convincingly improve on the baseline. No promotion or trading.

| Model | MAE (return) | RMSE (return) | Directional accuracy |
| --- | ---: | ---: | ---: |
| zero_return | 0.00618492 | 0.00986152 | Abstains |
| persistence | 0.00905402 | 0.01403384 | 48.94% |
| gru | 0.00615030 | 0.00989327 | 52.59% |
| lstm | 0.00616159 | 0.00989419 | 52.63% |
| xgboost | 0.00614436 | 0.00983463 | 51.69% |
| selected | 0.00615825 | 0.00988681 | 52.71% |

5,960 evaluation samples; direction measured on 5,879 moves larger than 0.01%.
Epoch losses use percentage-point targets plus regularization.

All 55 epoch records and full output are saved locally in
`data/processed/tensorflow-20261022T052236408074Z/`.

Model binaries and the complete archive were downloaded to `models/tensorflow-20261022T052236408074Z/` and `models/tensorflow-20261022T052236408074Z.zip`. Saved artifact checksums verified successfully. The latest-fold neural candidate is GRU; it remains unapproved.
