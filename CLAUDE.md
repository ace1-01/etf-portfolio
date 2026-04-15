# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

ETF 포트폴리오 관리 프로그램 — a single-page mobile-first web app for managing ETF portfolios with rebalancing, monthly allocation, goal simulation, and tax-advantaged account planning. All logic is in one self-contained `index.html` file with no build tools, dependencies, or backend.

## Running the App

Open `index.html` directly in a browser (no server required). The app uses `localStorage` for persistence and optionally calls the Anthropic Claude API for AI features.

## Architecture

Everything lives in `index.html`:

**State** (`state` object, persisted to `localStorage`):
- `stocks[]` — each item: `{id, name, value, dividendRate, isSafe, category, aiReason}`
- `ratios` — `{growth, dividend, hedge}` (integers 1-9, sum must equal 10)
- `investment` — `{total, monthly}` (raw digit strings, formatted on display)
- `goals[]` — `{id, name, targetAmount, targetYear, targetMonth, savingType}`
- `taxAccounts` — `{pensionTax, irp, pensionNoTax, isa}` each with contribution amounts
- `aiComment`, `aiRecs`, `checkedRecs` — cached AI responses

**Router**: `state.step` (1-6) drives everything. `go(n)` sets step and calls `renderStep()` which calls `renderStepN()` + `bindStepN()`.

**Steps**:
1. `renderStep1` / `bindStep1` — persistent form + live list; category heuristic (`guessCategory`) warns on mismatch; optional AI classification via Claude
2. `renderStep2` / `bindStep2` — dropdowns for growth/dividend/hedge (1-9 each, sum must = 10)
3. `renderStep3` / `bindStep3` — total and monthly investment amounts
4. `renderStep4` / `bindStep4` — goal funds with target date, amount, saving type; remaining time shown
5. `renderStep5` / `bindStep5` — tax-advantaged accounts (연금저축세액공제, IRP, 연금저축일반, ISA) with limit enforcement
6. `renderResults` / `bindResults` — computed results: donut charts, rebalancing plan, monthly allocation, goal simulation, tax account order, AI commentary, copy-to-clipboard

**Key utilities**:
- `fmt(raw)` / `unformat(val)` — Korean number formatting with comma separators
- `applyFormat(input, raw)` — formats input while preserving cursor position
- `calcPortfolio()` — computes current/target/diff per category and per-stock adjustments
- `calcGoalSim(goal)` — goal feasibility based on simple linear projection
- `drawDonut(canvasId, segments, colors)` — retina-aware canvas donut chart
- `callClaude(prompt)` — calls `https://api.anthropic.com/v1/messages` directly from the browser using a stored API key; model `claude-haiku-4-5-20251001`

**AI features** (require API key stored in `localStorage`):
- Step 1: auto-classify stock category + safe-asset flag
- Results page: portfolio rebalancing commentary (auto-triggered on load)
- Results page: monthly accumulation stock recommendations with checkbox selection

**Design**: Dark theme (`#0d1b2a` bg, `#f0c040` gold accent), max-width 480px, Noto Sans KR, no external framework.
