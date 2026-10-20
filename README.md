# Crypto Agent

An initial scaffold for a multi-user AI cryptocurrency trading project using Python, machine learning, FastAPI, Next.js, and React. The initial focus will be XRP/USDT price prediction and simulated trading. Coinbase integration may be considered later, after proper testing.

This scaffold contains placeholder files only. No application logic, model training, trading functionality, or exchange connections have been implemented. The frontend has not been initialized.

## Project layout

| Path | Intended contents |
| --- | --- |
| `data/raw/` | Original market datasets, to be added later. |
| `data/processed/` | Cleaned datasets and prepared features. |
| `models/` | Trained model artifacts, to be generated later. |
| `src/` | Python modules for data loading, preprocessing, feature engineering, and prediction. |
| `backend/` | Future FastAPI application, simulated trading orchestration, risk management, and Coinbase client. |
| `frontend/` | Future Next.js and React user interface. |
| `train.py` | Placeholder for the future training entry point. |
| `requirements.txt` | Planned Python dependencies; none are installed by this scaffold. |
| `.env.example` | Configuration variable names with empty values; no credentials. |
| `.gitignore` | Excludes local secrets, environments, caches, datasets, saved models, and generated artifacts. |

Empty directories include `.gitkeep` files so Git can track them. Python package directories include `__init__.py` files.

## Configuration

The example environment file lists placeholders for the application environment, database URL, trading symbol, trading mode, model path, and future Coinbase credentials. Values and configuration handling will be defined during implementation. Never commit real credentials.

## Current scope

Only the initial directory structure and placeholder files are provided. No datasets have been downloaded, dependencies installed, models trained, or Next.js application initialized.
