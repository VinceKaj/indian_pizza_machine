# Polymarket Arb — Probability & Arbitrage

App that takes **Polymarket** bets as input, finds **related bets** with causality, and surfaces **probability / arbitrage** opportunities.

## Project structure

| Folder      | Purpose |
|------------|--------|
| **`frontend/`** | React + Vite + Tailwind UI for inputs and results |
| **`backend/`**  | API, Polymarket data, and orchestration |
| **`ml/`**       | Causality, related-bet discovery, probability/arb models |

## Quick start

### Start entire app (from project root)

One-time setup: install root deps, frontend deps, and backend venv:

```bash
npm install
cd frontend && npm install && cd ..
cd backend && python -m venv .venv && .venv\Scripts\python -m pip install -r requirements.txt && cd ..
```
(On macOS/Linux use `.venv/bin/python -m pip` instead of `.venv\Scripts\python -m pip`.)

Then from the **topmost folder** (`indian_pizza_machine`):

```bash
npm run dev
```

This starts the frontend (http://localhost:5173) and backend (http://localhost:8000) together. Use Ctrl+C to stop both.

### Frontend only

```bash
cd frontend
npm install
npm run dev
```

Then open http://localhost:5173.

### Backend only (FastAPI)

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate   # macOS/Linux
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- API: http://localhost:8000  
- Docs: http://localhost:8000/docs  
- **Auto-updating endpoint:** `GET /api/updates` — returns data refreshed in the background every 10 seconds (poll for latest).

### ML

Add your run instructions here as you build.
