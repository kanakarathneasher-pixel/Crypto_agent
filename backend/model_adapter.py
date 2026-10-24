"""One documented prediction envelope; classifier probabilities are never returns."""
from datetime import datetime, timezone
from decimal import Decimal
from backend.config import config
from backend.managed_contracts import PredictionContract
from src.prediction import predict
from src.classifier_prediction import forecast


def infer(candles, now=None):
    now = now or datetime.now(timezone.utc)
    try:
        result = predict(candles, config.model_path, now)
        return PredictionContract(model_version=result['version'], input_timestamp=result['candle_time'],
            prediction_timestamp=now, output_kind='return', predicted_return=Decimal(str(result['predicted_return'])),
            predicted_price=Decimal(str(result['estimated_price'])), validated_for_orders=True, data_quality='valid')
    except (OSError, ValueError, KeyError):
        pass
    try:
        result = forecast(candles, now)
        return PredictionContract(model_version=result['version'], input_timestamp=result['candle_time'],
            prediction_timestamp=now, output_kind='direction_probability',
            probability_up=Decimal(str(result['probability_up'])), data_quality='valid',
            reason_codes=['MODEL_NOT_APPROVED', 'EXPECTED_RETURN_UNAVAILABLE', 'PROBABILITY_UNCALIBRATED'])
    except (OSError, ValueError, KeyError) as error:
        code = 'STALE_INPUT' if 'stale' in str(error).lower() else 'INVALID_OR_MISSING_INPUT'
        return PredictionContract(prediction_timestamp=now, output_kind='unavailable',
                                  data_quality='stale' if code == 'STALE_INPUT' else 'invalid', reason_codes=[code])
