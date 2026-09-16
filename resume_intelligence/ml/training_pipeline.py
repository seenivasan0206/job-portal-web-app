# -*- coding: utf-8 -*-
"""
Calibrated ML Training Pipeline.
Calibrates models on realistic distribution:
Average resumes: 55–68 | Good: 70–80 | Exceptional (with quantified metrics): 85+
"""
import os
import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier, GradientBoostingRegressor
from sklearn.model_selection import train_test_split
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import accuracy_score, f1_score, mean_absolute_error, r2_score

MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "models", "trained_models")
os.makedirs(MODEL_DIR, exist_ok=True)

def generate_calibrated_benchmark_data(n_samples=4000):
    """
    Generates realistic, calibrated benchmark data with anti-gaming features.
    Substantive prose (real leadership, architecture, depth) scores 75–85+,
    while thin resumes with fake repetitive percentage claims and padded skills are penalized to 50–62.
    """
    np.random.seed(42)
    X = []
    y_reg = []
    y_clf = []

    for _ in range(n_samples):
        # Sample resume archetypes
        archetype = np.random.choice(['strong_prose', 'top_quantified', 'average', 'thin_padded', 'bare_minimum'],
                                      p=[0.20, 0.20, 0.35, 0.15, 0.10])
        
        if archetype == 'top_quantified':
            words = np.random.randint(450, 950)
            num_skills = np.random.randint(9, 15)
            bullets = np.random.randint(5, 12)
            verbs = np.random.randint(5, 10)
            leadership_verbs = np.random.randint(2, 6)
            metrics = np.random.choice([3, 4, 5, 6])
            avg_bullet_words = np.random.uniform(10.0, 16.0)
            substantive_ratio = np.random.uniform(0.75, 1.0)
            short_ratio = np.random.uniform(0.0, 0.15)
            opening_repeat = np.random.uniform(0.1, 0.3)
            has_sum, has_exp, has_edu, has_skills = 1, 1, 1, 1
            has_proj = int(np.random.rand() > 0.2)
            has_certs = int(np.random.rand() > 0.3)
            contact_score = 4
        elif archetype == 'strong_prose':
            # Substantive senior engineer with leadership but 0 numbers
            words = np.random.randint(400, 850)
            num_skills = np.random.randint(8, 14)
            bullets = np.random.randint(5, 10)
            verbs = np.random.randint(5, 9)
            leadership_verbs = np.random.randint(2, 5)
            metrics = 0
            avg_bullet_words = np.random.uniform(10.0, 15.0)
            substantive_ratio = np.random.uniform(0.8, 1.0)
            short_ratio = 0.0
            opening_repeat = np.random.uniform(0.1, 0.25)
            has_sum, has_exp, has_edu, has_skills = 1, 1, 1, 1
            has_proj = int(np.random.rand() > 0.3)
            has_certs = int(np.random.rand() > 0.4)
            contact_score = np.random.choice([3, 4])
        elif archetype == 'thin_padded':
            # Low substance, padded 18-25 skills, 5 repetitive stub metrics
            words = np.random.randint(120, 260)
            num_skills = np.random.randint(18, 25)
            bullets = np.random.randint(4, 7)
            verbs = np.random.randint(1, 3)
            leadership_verbs = 0
            metrics = np.random.choice([4, 5, 6])
            avg_bullet_words = np.random.uniform(3.5, 5.5)
            substantive_ratio = 0.0
            short_ratio = np.random.uniform(0.8, 1.0)
            opening_repeat = np.random.uniform(0.6, 1.0)
            has_sum = int(np.random.rand() > 0.7)
            has_exp = 1
            has_edu = 1
            has_skills = 1
            has_proj = int(np.random.rand() > 0.8)
            has_certs = 0
            contact_score = np.random.choice([2, 3])
        elif archetype == 'average':
            words = np.random.randint(220, 500)
            num_skills = np.random.randint(5, 10)
            bullets = np.random.randint(3, 7)
            verbs = np.random.randint(2, 5)
            leadership_verbs = np.random.choice([0, 1])
            metrics = np.random.choice([0, 1], p=[0.7, 0.3])
            avg_bullet_words = np.random.uniform(6.0, 9.5)
            substantive_ratio = np.random.uniform(0.2, 0.6)
            short_ratio = np.random.uniform(0.1, 0.4)
            opening_repeat = np.random.uniform(0.2, 0.45)
            has_sum = int(np.random.rand() > 0.4)
            has_exp = 1
            has_edu = 1
            has_skills = 1
            has_proj = int(np.random.rand() > 0.5)
            has_certs = int(np.random.rand() > 0.6)
            contact_score = np.random.choice([2, 3, 4])
        else: # bare_minimum
            words = np.random.randint(40, 130)
            num_skills = np.random.randint(1, 4)
            bullets = np.random.randint(0, 3)
            verbs = np.random.randint(0, 2)
            leadership_verbs = 0
            metrics = 0
            avg_bullet_words = np.random.uniform(3.0, 6.0) if bullets > 0 else 0.0
            substantive_ratio = 0.0
            short_ratio = 1.0 if bullets > 0 else 0.0
            opening_repeat = 0.0
            has_sum = 0
            has_exp = int(np.random.rand() > 0.6)
            has_edu = int(np.random.rand() > 0.4)
            has_skills = int(np.random.rand() > 0.3)
            has_proj = 0
            has_certs = 0
            contact_score = np.random.choice([1, 2])

        num_tech = int(num_skills * np.random.uniform(0.7, 0.95))
        num_soft = num_skills - num_tech
        skill_count_capped = min(num_skills, 12)
        
        word_norm = min(1.0, words / 700.0) if words <= 700 else max(0.5, 1.0 - (words - 700) / 1000.0)
        b_verb_ratio = verbs / max(bullets, 1)
        m_density = metrics / max(bullets, 1)
        
        # JD Match signals (0 if no JD)
        has_jd = np.random.rand() > 0.5
        if has_jd:
            skill_ratio = np.random.uniform(0.2, 0.95)
            sem_sim = np.random.uniform(0.3, 0.90)
            missing_cnt = int((1.0 - skill_ratio) * 6)
            exp_match = np.random.uniform(0.4, 0.95)
            kw_cov = skill_ratio
        else:
            skill_ratio = 0.0
            sem_sim = 0.0
            missing_cnt = 0
            exp_match = 0.0
            kw_cov = 0.0

        feat = [
            words, num_skills, num_tech, num_soft, bullets, verbs, metrics,
            has_sum, has_exp, has_edu, has_skills, has_proj, has_certs,
            contact_score, word_norm, b_verb_ratio, m_density,
            avg_bullet_words, substantive_ratio, short_ratio, opening_repeat,
            leadership_verbs, skill_count_capped,
            skill_ratio, sem_sim, missing_cnt, exp_match, kw_cov
        ]
        
        # Calibrated realistic ground truth with anti-gaming adjustments
        effective_metrics = metrics * (1.0 - short_ratio * 0.6) * (1.0 - max(0.0, opening_repeat - 0.3))
        
        base = (
            (has_exp * 12) + (has_edu * 10) + (has_skills * 10) + (has_sum * 6) + (has_proj * 5) + (has_certs * 4) +
            (skill_count_capped * 1.5) + (min(verbs, 8) * 1.2) + (leadership_verbs * 2.5) +
            (min(effective_metrics, 4) * 3.5) + (substantive_ratio * 8.0) + (contact_score * 2.0)
        )
        
        # Penalties for spam/padding/stubs
        if short_ratio > 0.7 and bullets >= 3:
            base -= 10.0
        if opening_repeat > 0.5 and bullets >= 3:
            base -= 8.0
        if num_skills > 16:
            base -= (num_skills - 16) * 1.2
            
        if has_jd:
            base += (sem_sim * 10) + (skill_ratio * 12)
        else:
            base = base * 1.10

        noise = np.random.normal(0, 1.5)
        score = max(15, min(96, int(base + noise)))
        
        if score >= 82: tier = 3 # Excellent
        elif score >= 70: tier = 2 # Good
        elif score >= 52: tier = 1 # Moderate
        else: tier = 0 # Needs Improvement
        
        X.append(feat)
        y_reg.append(score)
        y_clf.append(tier)

    return np.array(X), np.array(y_reg), np.array(y_clf)

def train_and_serialize_models():
    """Train calibrated regressor and calibrated classifier."""
    X, y_reg, y_clf = generate_calibrated_benchmark_data(4000)
    X_train, X_test, y_reg_train, y_reg_test, y_clf_train, y_clf_test = train_test_split(
        X, y_reg, y_clf, test_size=0.2, random_state=42
    )

    # 1. Regressor
    reg_model = GradientBoostingRegressor(n_estimators=160, max_depth=4, learning_rate=0.07, random_state=42)
    reg_model.fit(X_train, y_reg_train)
    reg_preds = reg_model.predict(X_test)
    mae = mean_absolute_error(y_reg_test, reg_preds)
    r2 = r2_score(y_reg_test, reg_preds)

    # 2. Classifier with Sigmoid Probability Calibration
    base_clf = RandomForestClassifier(n_estimators=140, max_depth=6, random_state=42)
    calibrated_clf = CalibratedClassifierCV(estimator=base_clf, method='sigmoid', cv=3)
    calibrated_clf.fit(X_train, y_clf_train)
    clf_preds = calibrated_clf.predict(X_test)
    acc = accuracy_score(y_clf_test, clf_preds)
    f1 = f1_score(y_clf_test, clf_preds, average='weighted')

    model_payload = {
        'version': 'ATS Engine v2.6 (Calibrated ML Anti-Gaming)',
        'reg_model': reg_model,
        'clf_model': calibrated_clf,
        'feature_count': X.shape[1],
        'metrics': {
            'mae': round(float(mae), 3),
            'r2': round(float(r2), 3),
            'accuracy': round(float(acc), 3),
            'f1_score': round(float(f1), 3),
            'train_samples': len(X_train),
            'test_samples': len(X_test)
        }
    }

    save_path = os.path.join(MODEL_DIR, "ats_model_v1.joblib")
    joblib.dump(model_payload, save_path)
    return model_payload

if __name__ == '__main__':
    p = train_and_serialize_models()
    print(f"Trained calibrated model: R2={p['metrics']['r2']}, F1={p['metrics']['f1_score']}, Accuracy={p['metrics']['accuracy']}")

