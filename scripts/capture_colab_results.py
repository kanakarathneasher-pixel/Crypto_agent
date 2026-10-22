"""Preserve completed Colab notebook output locally, without rerunning training."""
import csv
import json
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
notebook = json.loads((root / 'notebooks/coinbase_colab.ipynb').read_text(encoding='utf-8'))
cell = next(c for c in notebook['cells'] if c['cell_type'] == 'code'
            and ''.join(c['source']).startswith('START_TRAINING'))
output = ''.join(''.join(o.get('text', [])) for o in cell['outputs'])
if 'Saved research model:' not in output:
    raise RuntimeError('Notebook does not contain a completed research run.')
remote, remainder = output.split('Saved research model: ', 1)[1].split('\n', 1)
metrics, _ = json.JSONDecoder().raw_decode(remainder.lstrip())
version = Path(remote).name
folder = root / 'data/processed' / version
folder.mkdir(parents=True, exist_ok=True)
(folder / 'training_output.txt').write_text(output, encoding='utf-8')
(folder / 'development_metrics.json').write_text(json.dumps(metrics, indent=2), encoding='utf-8')
pattern = r'fold_(\d+)/(gru|lstm) epoch (\d+): loss=([\d.]+), validation_loss=([\d.]+)'
epochs = re.findall(pattern, output)
with (folder / 'epoch_history.csv').open('w', newline='', encoding='utf-8') as handle:
    writer = csv.writer(handle)
    writer.writerow(['fold', 'architecture', 'epoch', 'training_loss', 'validation_loss'])
    writer.writerows(epochs)
lines = ['# TensorFlow development results', '', f'Run: `{version}`. Completed on Colab GPU.',
         '', 'These are historical development evaluations, not a fresh final test.',
         'Both neural networks failed to convincingly improve on the baseline. No promotion or trading.',
         '', '| Model | MAE (return) | RMSE (return) | Directional accuracy |',
         '| --- | ---: | ---: | ---: |']
for name in ['zero_return', 'persistence', 'gru', 'lstm', 'xgboost', 'selected']:
    m = metrics[name]
    accuracy = 'Abstains' if name == 'zero_return' else f"{m['directional_accuracy']:.2%}"
    lines.append(f"| {name} | {m['mae']:.8f} | {m['rmse']:.8f} | {accuracy} |")
lines += ['', '5,960 evaluation samples; direction measured on 5,879 moves larger than 0.01%.',
          'Epoch losses use percentage-point targets plus regularization.', '',
          f'All {len(epochs)} epoch records and full output are saved locally in',
          f'`data/processed/{version}/`.', '',
          f'Model binaries remain in Colab at `{remote}` until downloaded.']
(root / 'docs/tensorflow_results.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
print('Preserved', len(epochs), 'epoch records in', folder)
print(json.dumps({n: {k: metrics[n][k] for k in ['mae', 'rmse', 'directional_accuracy']}
                  for n in ['gru', 'lstm', 'xgboost', 'zero_return']}, indent=2))
