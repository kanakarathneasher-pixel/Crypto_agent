import numpy as np
import pandas as pd
import pytest

from src.direction_research import horizon_frame, score, spot_simulation, FEE, SLIPPAGE
from src.neural_data import SEQUENCE_FEATURES, make_fold
from tests.test_pipeline import candles


@pytest.mark.parametrize('horizon', [1, 4, 24])
def test_labels_and_splits_respect_horizon_and_gaps(horizon):
    raw = candles(700).drop(index=list(range(250, 255)))
    data = horizon_frame(raw, horizon)
    assert (data.target_time-data.open_time == pd.Timedelta(hours=horizon)).all()
    for row in data.itertuples():
        required = pd.date_range(row.open_time, row.target_time, freq='h')
        assert required.isin(raw.open_time).all()
        target = raw.set_index('open_time').close.loc[row.target_time]
        assert row.target_next_return == pytest.approx(target/row.close-1)
    fold = make_fold(data, np.arange(len(data)), .5, .7)
    assert data.target_time.iloc[fold.train].max() < data.open_time.iloc[fold.validation].min()
    assert data.target_time.iloc[fold.validation].max() < data.open_time.iloc[fold.evaluation].min()
    changed = raw.copy()
    changed.loc[changed.open_time >= pd.Timestamp('2025-01-20', tz='UTC'), ['open', 'high', 'low', 'close']] *= 2
    later = horizon_frame(changed, horizon)
    a = data.loc[data.open_time < pd.Timestamp('2025-01-20', tz='UTC')]
    b = later.loc[later.open_time.isin(a.open_time)]
    pd.testing.assert_frame_equal(a[SEQUENCE_FEATURES], b[SEQUENCE_FEATURES])


def test_accuracy_and_coverage_do_not_hide_neutral_hours():
    result = score([.01, -.01, 0., .02], [.9, .1, .95, .51], .7)
    assert result['accuracy'] == 1.
    assert result['coverage_all_hours'] == .75
    assert result['scored_predictions'] == 2
    assert result['neutral_samples'] == 1
    assert result['confusion_matrix_down_up'] == [[1, 0], [0, 1]]
    majority = score([.01, -.01, .01, .01], [1., 1., 1., 1.])
    assert majority['accuracy'] == .75
    assert majority['balanced_accuracy'] == .5


def test_spot_simulation_costs_and_nonoverlap():
    data = horizon_frame(candles(120), 4).head(12)
    result = spot_simulation(data, np.ones(len(data)))
    assert len(result['fills']) == 3
    first = result['fills'][0]
    expected = 100 / (data.entry_open.iloc[0]*(1+SLIPPAGE)*(1+FEE))
    expected = expected*data.exit_close.iloc[0]*(1-SLIPPAGE)*(1-FEE)-100
    assert first['pnl_usdc'] == pytest.approx(expected)
    for previous, following in zip(result['fills'], result['fills'][1:]):
        assert pd.Timestamp(following['entry_utc']) >= pd.Timestamp(previous['exit_utc'])
    assert spot_simulation(data, np.zeros(len(data)))['round_trips'] == 0


def test_complete_abstention_is_reported_without_inventing_accuracy():
    result = score([.01, -.01], [.51, .49], .7)
    assert result['coverage_all_hours'] == 0
    assert result['accuracy'] is None
    assert result['balanced_accuracy'] is None
    assert result['confusion_matrix_down_up'] == [[0, 0], [0, 0]]
