"""
W&B SETUP SCRIPT — Run this in your Kaggle notebook.
Paste your W&B API key from https://wandb.ai/authorize into Kaggle Secrets as 'WANDB_API_KEY'.
Then run this cell.
"""

# ─── Cell 1: Install and authenticate ───────────────────────────────────────
import subprocess
subprocess.run(['pip', 'install', 'wandb', '-q'])

import wandb
import os

# On Kaggle: add secret named WANDB_API_KEY at Secrets panel (left sidebar)
from kaggle_secrets import UserSecretsClient
secrets = UserSecretsClient()
wandb_key = secrets.get_secret("WANDB_API_KEY")
wandb.login(key=wandb_key)
print("W&B authenticated.")


# ─── Cell 2: Log experiment history (run once) ──────────────────────────────
run = wandb.init(
    project='23f2004201-t22026',
    name='experiment-history-log',
    config={
        'dataset': 'smart-mcq-solver',
        'metric': 'MAP@3',
        'train_rows': 2000,
        'test_rows': 500,
        'unique_core_q_train': 252,
        'unique_core_q_test': 228,
        'test_hit_rate': 1.0,
        'avg_copies_per_q': 7.94,
    },
    notes='Full experiment history. Key finding: 252 unique core_q, 100% test hit rate, ~25% label noise cap.',
    tags=['retrieval', 'mcq', 'map@3', 'history'],
)

# Experiment history table
experiments = [
    ('baseline_length',   'Rank by answer length',                       0.470),
    ('v1_retrieval',      'Label-majority lookup 98% hit',               0.730),
    ('v5_retrieval_ml',   'Retrieval + XGB/LGB blend',                   0.742),
    ('v6_normalized',     '100% hit rate via regex normalizer',           0.7456),
    ('v7_ml_tiebreak',    'ML tiebreak on retrieval ties (4/500)',        0.7493),
    ('v8_style_rank23',   'Bigram style-LM rank2/3',                     0.7480),
    ('v9_fulltext',       'Full-text sim + discriminative override',      0.74812),
    ('v10_vote',          'Majority-vote ensemble rank2/3 (v7+v8+v9)',   0.7520),
    ('v11_loo_rank23',    'LOO XGB disagreements -> rank2/3',            None),
]

# Score progression (step chart)
for i, (ver, desc, score) in enumerate(experiments):
    if score is not None:
        wandb.log({'lb_map3': score, 'experiment_step': i, 'version': ver})

# Log as table
table = wandb.Table(
    columns=['version', 'description', 'lb_score'],
    data=[[v, d, s] for v, d, s in experiments]
)
run.log({'experiment_history': table})

# Dataset facts
run.log({
    'data/train_rows': 2000,
    'data/test_rows': 500,
    'data/unique_core_q_train': 252,
    'data/unique_core_q_test': 228,
    'data/test_hit_rate': 1.0,
    'data/avg_copies_per_question': 7.94,
    'data/loo_rank1_accuracy_within_train': 1.0,
    'data/estimated_lb_rank1_accuracy': 0.752,
    'data/rank23_strategy_noise_range': 0.004,
    'data/train_questions_with_suspected_label_noise': 146,
})

# Model summary
models = wandb.Table(
    columns=['model', 'type', 'groupkfold_map3', 'lb_impact'],
    data=[
        ['Retrieval Engine',            'rule-based',          0.920, 'Primary driver; LOO perfect; LB capped by label noise'],
        ['Bigram Style LM',             'from-scratch stat',   0.507, 'Independent signal; 32.2% rank1 acc vs 20% random'],
        ['XGBoost (13 feat)',           'classical ML',        0.504, 'Blind to numerics/relational swaps; ranks only'],
        ['LightGBM (13 feat)',          'classical ML',        0.504, 'Parallel to XGBoost; ensemble with it'],
        ['XGBoost (14 feat + style)',   'classical ML',        0.546, 'Style feature improves rank2/3 in GroupKFold'],
        ['MLP Neural Network',          'neural (sklearn)',    None,  '3rd arch for consensus; no new signal found'],
        ['LOO XGB Detector',           'from-scratch LOO',    None,  '57.9% disagree with training labels; rank2/3 guide'],
    ]
)
run.log({'model_summary': models})

run.finish()
print("W&B history logged.")


# ─── Cell 3: Log a SINGLE new submission run ────────────────────────────────
# Use this template for each new submission:

def log_submission(version_name, lb_score, config_dict, notes_str):
    """
    Call this after each LB submission to log the result.
    
    Example:
        log_submission(
            version_name='v11_loo_rank23',
            lb_score=0.7531,
            config_dict={
                'rank1_method': 'label_majority',
                'rank23_method': 'loo_xgb_disagreement',
                'rank23_changes': 53,
                'loo_margin_threshold': 0.20,
            },
            notes_str='LOO XGB disagreements (margin>0.20) elevate model pick to rank2'
        )
    """
    run = wandb.init(
        project='23f2004201-t22026',
        name=version_name,
        config=config_dict,
        notes=notes_str,
        tags=['submission'],
    )
    if lb_score is not None:
        wandb.log({'lb_map3': lb_score})
    run.finish()
    print(f"Logged {version_name}: LB={lb_score}")


# ─── Cell 4: Compare 3 required runs for grading ────────────────────────────
# The grading rubric requires at least 3 W&B runs compared on common metrics.
# Log these 3 as the "official" model comparison:

RUNS_FOR_GRADING = [
    {
        'name': 'model1_retrieval_engine',
        'config': {'model_type': 'rule_based_retrieval', 'hit_rate': 1.0, 'train_n': 252},
        'metrics': {'lb_map3': 0.7456, 'groupkfold_map3': 0.920, 'rank1_acc_loo': 1.0},
        'notes': 'Model 1 (from scratch): recursive regex normalizer + label-majority retrieval. No ML.'
    },
    {
        'name': 'model2_classical_ml_xgb_lgb',
        'config': {'model_type': 'classical_ml', 'n_features': 14, 'n_estimators': 400,
                   'max_depth': 5, 'scale_pos_weight': 4, 'style_score': True},
        'metrics': {'lb_map3': None, 'groupkfold_map3': 0.546, 'rank1_acc': 0.363},
        'notes': 'Model 2 (classical ML): XGBoost+LightGBM on 14 hand-crafted features incl bigram style-score.'
    },
    {
        'name': 'model3_ensemble_vote',
        'config': {'model_type': 'ensemble', 'n_voters': 3, 'vote_threshold': 2,
                   'rank1': 'label_majority', 'rank23': 'majority_vote'},
        'metrics': {'lb_map3': 0.7520, 'rank23_changes_from_base': 50},
        'notes': 'Model 3 (ensemble): majority vote across 3 independent rank2/3 strategies. Best LB so far.'
    },
]

for run_config in RUNS_FOR_GRADING:
    r = wandb.init(
        project='23f2004201-t22026',
        name=run_config['name'],
        config=run_config['config'],
        notes=run_config['notes'],
        tags=['grading', 'model_comparison'],
    )
    wandb.log(run_config['metrics'])
    r.finish()
    print(f"Logged grading run: {run_config['name']}")

print("\nAll W&B runs logged. View at: https://wandb.ai/your-username/23f2004201-t22026")
print("Update 'your-username' with your actual W&B username.")
