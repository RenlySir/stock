# Pythonstock Indicator Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the useful technical-indicator ideas from `pythonstock/stock` into the current lightweight A-share CLI system without adding its Web/MySQL architecture.

**Architecture:** Extend the existing `stock_ai.factors` pipeline with low-cost pandas indicators, then incorporate those fields in `stock_ai.strategy.score_candidates()`. Keep the current SQLite, CLI, cron, systemd, fixed-stock-pool, and WeChat notification architecture unchanged.

**Tech Stack:** Python 3, pandas, unittest, existing `stock_ai` modules.

---

### Task 1: Technical Factor Columns

**Files:**
- Modify: `stock_ai/factors.py`
- Test: `tests/test_strategy_indicators.py`

- [ ] **Step 1: Write failing tests**

Add tests that call `add_factor_columns()` on deterministic A-share OHLCV data and assert that KDJ, BOLL, MACD, RSI, CCI, WR, VR, and TRIX-like columns exist, are finite on the latest rows, and capture a stronger trend for the rising sample than the weak sample.

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `python3 -m unittest tests.test_strategy_indicators`

Expected: FAIL because the new technical factor columns do not exist yet.

- [ ] **Step 3: Implement minimal factor columns**

Add pandas implementations in `stock_ai/factors.py`, using grouped rolling/ewm operations and replacing inf/nan outputs with neutral values.

- [ ] **Step 4: Verify focused tests pass**

Run: `python3 -m unittest tests.test_strategy_indicators`

Expected: PASS.

### Task 2: Strategy Scoring Integration

**Files:**
- Modify: `stock_ai/strategy.py`
- Test: `tests/test_strategy_indicators.py`

- [ ] **Step 1: Write failing scoring tests**

Add tests that `score_candidates()` returns `technical_score`, includes technical reasons, and applies a visible overheating risk penalty for extreme RSI/KDJ/WR-style states.

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `python3 -m unittest tests.test_strategy_indicators`

Expected: FAIL because scoring does not expose or use the technical score yet.

- [ ] **Step 3: Implement minimal scoring changes**

Blend the new technical score into `combined_score`, expose `technical_score`, and add concise reason/risk text without changing CLI contracts.

- [ ] **Step 4: Run full tests**

Run: `python3 -m unittest discover -s tests`

Expected: all tests pass.

### Task 3: Deploy and Commit

**Files:**
- Modify: server files under `/opt/stock`

- [ ] **Step 1: Deploy changed code to server**

Package and copy `stock_ai`, `tests`, `scripts`, `docs`, `run_stock_ai.py`, `README.md`, and `requirements.txt` to `/opt/stock`.

- [ ] **Step 2: Run server tests and restart services**

Run server-side unittest discovery and restart `stock-ai-realtime.service`.

- [ ] **Step 3: Commit and push**

Commit only tracked project files touched by this task and push to `origin main`.
