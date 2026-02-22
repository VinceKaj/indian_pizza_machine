# Data pipeline: Prompt → Basket weights

End-to-end flow from the user’s search prompt to the returned basket weights (and optional time series).

```mermaid
flowchart TB
    subgraph frontend["Frontend"]
        A[User enters prompt]
        A --> B[POST /api/search/semantic]
        B --> C{Parse response}
        C --> D[events + word_search_markets]
        D --> E[Best match = max score in word_search_markets]
        E --> F{best.score > 0.7?}
        F -->|Yes| G[POST /api/basket]
        F -->|No| H[POST /api/basket-no-target]
        G --> I[Weights + target/synthetic series]
        H --> I
    end

    subgraph semantic["Backend: Semantic search"]
        B -.-> S1[Embed prompt]
        S1 --> S2[Cosine vs tag embeddings]
        S2 --> S3[Top N tags]
        S3 --> S4[Fetch events per tag<br/>Gamma API]
        S4 --> S5[Dedupe by event id]
        S5 --> S6[Per event: pick best market by MIS]
        S6 --> S7[Word search: full-text markets]
        S7 --> S8[Score word_search_markets by embedding]
        S8 --> D
    end

    subgraph basket_with_target["Backend: /api/basket (strong target)"]
        G -.-> T1[Fetch target + input metadata<br/>Gamma → CLOB IDs]
        T1 --> T2[Filter inputs by semantic similarity<br/>to target]
        T2 --> T3[Fetch price histories<br/>CLOB prices-history]
        T3 --> T4[Resample 1h, align to target index]
        T4 --> T5[OLS: min ‖y − Xw‖²]
        T5 --> T6[weights, target_prices, synthetic_prices,<br/>timestamps, r_squared]
        T6 --> I
    end

    subgraph basket_no_target["Backend: /api/basket-no-target"]
        H -.-> N1[Fetch input market metadata<br/>Gamma]
        N1 --> N2[Diversity filter<br/>centroid + pairwise similarity]
        N2 --> N3[Embed selected markets]
        N3 --> N4[Centroid + softmax weights]
        N4 --> N5[Fetch price histories → align]
        N5 --> N6[Weighted sum → synthetic series]
        N6 --> N7[weights, synthetic_prices, timestamps,<br/>centroid_question]
        N7 --> I
    end

    I --> J[Display weights + chart]
```

## Stages in words

| Stage | Where | What |
|--------|--------|--------|
| **1. Prompt** | Frontend | User types a query (e.g. “Fed rate decision March”). |
| **2. Semantic search** | `POST /api/search/semantic` | Embed prompt → match to cached Polymarket tags → fetch events per tag (Gamma) → dedupe → for each event pick one “best” market (MIS) → also run word search and score those markets by embedding. Return `events` (with `best_market`) and `word_search_markets` (with `score`). |
| **3. Decide path** | Frontend | Take best-scoring word-search market. If `best.score > 0.7` → call **basket (with target)**; else → call **basket-no-target**. Build `input_market_ids` from `events[].best_market.id` (unique, up to 15). |
| **4a. Basket with target** | `POST /api/basket` | One target market + list of input markets. Fetch metadata (Gamma) and CLOB IDs → filter inputs by semantic similarity to target → fetch 7d price history (CLOB) → resample to 1h and align to target → OLS to get weights. Return `weights`, `target_prices`, `synthetic_prices`, `timestamps`, `r_squared`. |
| **4b. Basket no-target** | `POST /api/basket-no-target` | Only input markets. Fetch metadata → diversity filter (centroid + max pairwise similarity) → embed selected markets → softmax( similarity to centroid ) → optional lognormal noise and renormalize → fetch price histories → align → weighted sum for synthetic series. Return `weights`, `synthetic_prices`, `timestamps`, `centroid_question`. |
| **5. Show result** | Frontend | Render basket weights (and optional time-series chart). |

## Data sources

- **Tag cache**: Polymarket events → unique tags → embedded tag labels (refreshed periodically).
- **Gamma API**: Events by tag, event by slug; market metadata (question, description, `clobTokenIds`).
- **CLOB API**: `prices-history` (market token ID + `startTs`/`endTs` or `interval`).
- **Embedding model**: e.g. BAAI/bge or similar for prompt, questions, and tag labels.

## Key outputs

- **Weights**: List of `{ title, market_id, weight[, similarity] }` summing to 1 (or near 1 after noise).
- **With target**: `target_prices`, `synthetic_prices`, `timestamps`, `r_squared`, `target_question`.
- **No target**: `synthetic_prices`, `timestamps`, `centroid_question`, `temperature`.
