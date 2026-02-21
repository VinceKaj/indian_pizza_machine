# Polymarket Arb — Probability & Arbitrage

App that takes **Polymarket** bets as input, finds **related bets** with causality, and surfaces **probability / arbitrage** opportunities.

## Project structure

| Folder      | Purpose |
|------------|--------|
| **`frontend/`** | React + Vite + Tailwind UI for inputs and results |
| **`backend/`**  | API, Polymarket data, and orchestration |
| **`ml/`**       | Causality, related-bet discovery, probability/arb models |

## Quick start

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Then open http://localhost:5173.

### Backend & ML

Add your run instructions here as you build (e.g. `uv run`, `poetry run`, `npm run dev`).
