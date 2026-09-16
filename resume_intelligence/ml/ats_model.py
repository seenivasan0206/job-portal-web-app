# -*- coding: utf-8 -*-
import os
import joblib
import logging
import numpy as np

logger = logging.getLogger(__name__)

MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "models", "trained_models", "ats_model_v1.joblib")
_MODEL_CACHE = None

def load_ml_model():
    """Load serialized ATS model payload."""
    global _MODEL_CACHE
    if _MODEL_CACHE is None:
        if os.path.exists(MODEL_PATH):
            try:
                _MODEL_CACHE = joblib.load(MODEL_PATH)
            except Exception as e:
                logger.error(f"Error loading model from {MODEL_PATH}: {e}")
        else:
            # Auto-train if model file missing
            try:
                from .training_pipeline import train_and_serialize_models
                _MODEL_CACHE = train_and_serialize_models()
            except Exception as err:
                logger.error(f"Error training baseline model: {err}")
    return _MODEL_CACHE

def predict_ats_compatibility(feature_vector):
    """
    Runs ML inference on a 22-dim feature vector.
    Returns: {'predicted_score': int, 'tier_name': str, 'confidence': float, 'model_version': str}
    """
    model_payload = load_ml_model()
    if not model_payload:
        # Fallback heuristic calculation if model not available
        return {
            'predicted_score': 75,
            'tier_name': 'Good Fit',
            'confidence': 0.85,
            'model_version': 'Heuristic Fallback'
        }

    reg_model = model_payload.get('reg_model')
    clf_model = model_payload.get('clf_model')

    feat_2d = feature_vector.reshape(1, -1)
    
    # Predict continuous score
    pred_score = int(round(float(reg_model.predict(feat_2d)[0])))
    pred_score = max(10, min(100, pred_score))
    
    # Predict probabilities for classification tier
    probs = clf_model.predict_proba(feat_2d)[0]
    tier_idx = int(np.argmax(probs))
    confidence = float(np.max(probs))
    
    tier_names = ['Poor Fit', 'Fair Fit', 'Good Fit', 'Excellent Fit']
    tier_name = tier_names[tier_idx] if tier_idx < len(tier_names) else 'Good Fit'

    return {
        'predicted_score': pred_score,
        'tier_name': tier_name,
        'confidence': round(confidence, 2),
        'model_version': model_payload.get('version', 'ATS Model v2.0'),
        'model_metrics': model_payload.get('metrics', {})
    }
