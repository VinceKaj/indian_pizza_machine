import { useEffect, useState, useMemo, useRef, useCallback } from 'react'
import { Routes, Route, useNavigate, useLocation, useParams } from 'react-router-dom'
import { ResponsiveContainer, ComposedChart, Area, Line, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts'
import ForceGraph2D from 'react-force-graph-2d'

function Section({ title, children, className = '' }) {
  return (
    <section className={`py-8 ${className}`}>
      <h2 className="mb-4 text-sm font-medium uppercase tracking-wider text-black border-b border-blue-700 pb-2">
        {title}
      </h2>
      {children}
    </section>
  )
}

/** Parse outcomes and outcomePrices from API (often JSON strings) */
function parseOutcomes(market) {
  let outcomes = market.outcomes
  let prices = market.outcomePrices
  if (typeof outcomes === 'string') {
    try { outcomes = JSON.parse(outcomes) } catch { outcomes = [outcomes] }
  }
  if (typeof prices === 'string') {
    try { prices = JSON.parse(prices) } catch { prices = [] }
  }
  if (!Array.isArray(outcomes)) outcomes = []
  if (!Array.isArray(prices)) prices = []
  return outcomes.map((label, i) => ({ label, price: prices[i] != null ? Number(prices[i]) : null }))
}

/** Format date string for display */
function formatDate(s) {
  if (!s) return ''
  try {
    const d = new Date(s)
    return d.toLocaleDateString(undefined, { dateStyle: 'medium' })
  } catch {
    return String(s)
  }
}

function BlueSwipe() {
  return (
    <div
      className="page-swipe fixed inset-0 z-[100] bg-blue-700"
      style={{ backgroundColor: '#1d4ed8' }}
      aria-hidden
    />
  )
}

const COINBASE_WS_URL = 'wss://ws-feed.exchange.coinbase.com'
const CRYPTO_PAIRS = ['BTC-USD', 'ETH-USD', 'SOL-USD', 'DOGE-USD', 'XRP-USD', 'AVAX-USD', 'LINK-USD', 'MATIC-USD', 'DOT-USD', 'LTC-USD']

const FLASH_MS = 400

function CryptoMarquee() {
  const [tickers, setTickers] = useState(() =>
    Object.fromEntries(CRYPTO_PAIRS.map((id) => [id, { price: null, open24h: null }]))
  )
  const [flash, setFlash] = useState({}) // product_id -> 'up' | 'down'
  const [connected, setConnected] = useState(false)
  const wsRef = useRef(null)
  const reconnectTimeoutRef = useRef(null)
  const flashTimeoutsRef = useRef({})

  useEffect(() => {
    function connect() {
      const ws = new WebSocket(COINBASE_WS_URL)
      wsRef.current = ws

      ws.onopen = () => {
        setConnected(true)
        ws.send(
          JSON.stringify({
            type: 'subscribe',
            product_ids: CRYPTO_PAIRS,
            channels: ['ticker', 'heartbeat'],
          })
        )
      }

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data)
          if (msg.type === 'ticker' && msg.product_id && msg.price != null) {
            const newPrice = parseFloat(msg.price)
            setTickers((prev) => {
              const prevPrice = prev[msg.product_id]?.price != null ? parseFloat(prev[msg.product_id].price) : null
              const direction = prevPrice != null ? (newPrice > prevPrice ? 'up' : newPrice < prevPrice ? 'down' : null) : null
              if (direction) {
                if (flashTimeoutsRef.current[msg.product_id]) clearTimeout(flashTimeoutsRef.current[msg.product_id])
                setFlash((f) => ({ ...f, [msg.product_id]: direction }))
                flashTimeoutsRef.current[msg.product_id] = setTimeout(() => {
                  setFlash((f) => {
                    const next = { ...f }
                    delete next[msg.product_id]
                    return next
                  })
                }, FLASH_MS)
              }
              return {
                ...prev,
                [msg.product_id]: {
                  price: msg.price,
                  open24h: msg.open_24h ?? prev[msg.product_id]?.open24h ?? null,
                },
              }
            })
          }
        } catch (_) {}
      }

      ws.onclose = () => {
        setConnected(false)
        wsRef.current = null
        reconnectTimeoutRef.current = setTimeout(connect, 3000)
      }

      ws.onerror = () => {}
    }

    connect()
    return () => {
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current)
      Object.values(flashTimeoutsRef.current).forEach(clearTimeout)
      flashTimeoutsRef.current = {}
      if (wsRef.current) wsRef.current.close()
      wsRef.current = null
    }
  }, [])

  const items = CRYPTO_PAIRS.map((id) => {
    const t = tickers[id]
    const price = t?.price != null ? parseFloat(t.price) : null
    const open = t?.open24h != null ? parseFloat(t.open24h) : null
    let changePct = null
    if (price != null && open != null && open > 0) {
      changePct = ((price - open) / open) * 100
    }
    const symbol = id.replace('-USD', '')
    const flashDir = flash[id]
    return {
      id,
      symbol,
      price,
      changePct,
      flashDir,
    }
  })

  return (
    <div className="relative bg-blue-700 text-white py-3 overflow-hidden shrink-0" style={{ backgroundColor: '#1d4ed8' }}>
      <div className="flex items-center gap-4 overflow-hidden">
        <div className="flex shrink-0 items-center gap-2 px-4">
          <span className="flex h-6 w-6 items-center justify-center bg-white/20 text-white">
            <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
            </svg>
          </span>
          <span className="text-sm font-medium text-white">Live</span>
        </div>
        <div className="ticker-wrap flex-1 min-w-0 overflow-hidden bg-blue-700" style={{ backgroundColor: '#1d4ed8' }}>
          <div className="ticker flex gap-8 whitespace-nowrap" style={{ width: 'max-content' }}>
          {items.map(({ id, symbol, price, changePct, flashDir }) => {
            const flashClass = flashDir === 'up' ? 'bg-emerald-500/90 text-white' : flashDir === 'down' ? 'bg-red-500/90 text-white' : ''
            return (
              <span
                key={id}
                className={`inline-flex items-center gap-2 px-4 shrink-0 transition-colors duration-150 rounded ${flashClass}`}
              >
                <span className="font-semibold">{symbol}</span>
                <span className="tabular-nums">
                  {price != null ? `$${Number(price).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—'}
                </span>
                {changePct != null && (
                  <span className={changePct >= 0 ? 'text-emerald-200' : 'text-red-200'}>
                    {changePct >= 0 ? '+' : ''}{changePct.toFixed(2)}%
                  </span>
                )}
              </span>
            )
          })}
          {items.map(({ id, symbol, price, changePct, flashDir }) => {
            const flashClass = flashDir === 'up' ? 'bg-emerald-500/90 text-white' : flashDir === 'down' ? 'bg-red-500/90 text-white' : ''
            return (
              <span
                key={`dup-${id}`}
                className={`inline-flex items-center gap-2 px-4 shrink-0 transition-colors duration-150 rounded ${flashClass}`}
                aria-hidden
              >
                <span className="font-semibold">{symbol}</span>
                <span className="tabular-nums">
                  {price != null ? `$${Number(price).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—'}
                </span>
                {changePct != null && (
                  <span className={changePct >= 0 ? 'text-emerald-200' : 'text-red-200'}>
                    {changePct >= 0 ? '+' : ''}{changePct.toFixed(2)}%
                  </span>
                )}
              </span>
            )
          })}
          </div>
        </div>
      </div>
      {!connected && (
        <div className="absolute top-1 right-2 text-[10px] text-amber-200">Reconnecting…</div>
      )}
    </div>
  )
}

function EventPage() {
  const { slug } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const [apiResponse, setApiResponse] = useState(location.state?.apiResponse ?? null)
  const [loading, setLoading] = useState(!location.state?.apiResponse)
  const [error, setError] = useState(null)
  const [priceHistory, setPriceHistory] = useState(null)
  const [chartInterval, setChartInterval] = useState('1d')
  const [navSearchValue, setNavSearchValue] = useState('')
  const [dashboardNews, setDashboardNews] = useState([])
  const [dashboardNewsLoading, setDashboardNewsLoading] = useState(true)
  const [relatedCandidates, setRelatedCandidates] = useState([])
  const [relatedHistories, setRelatedHistories] = useState({})
  const [selectedRelatedIds, setSelectedRelatedIds] = useState(new Set())

  function handleNavSearchSubmit(e) {
    e.preventDefault()
    const input = navSearchValue.trim()
    if (!input) return
    navigate('/search', { state: { prompt: input } })
  }

  useEffect(() => {
    if (apiResponse || !slug) return
    let cancelled = false
    async function fetchEvent() {
      try {
        const res = await fetch(`/api/polymarket?url=${encodeURIComponent(`https://polymarket.com/event/${slug}`)}`)
        const data = await res.json()
        if (cancelled) return
        if (!res.ok) {
          setError(data?.detail ?? 'Failed to load')
          return
        }
        setApiResponse(data)
      } catch (e) {
        if (!cancelled) setError(e.message ?? 'Request failed')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    fetchEvent()
    return () => { cancelled = true }
  }, [slug, apiResponse])

  // Fetch real price history when we have a CLOB token id (refetch when chartInterval changes)
  useEffect(() => {
    if (!apiResponse?.data) return
    const events = Array.isArray(apiResponse.data) ? apiResponse.data : [apiResponse.data]
    const event = events[0]
    const markets = event?.markets ?? []
    const market = markets[0]
    if (!market?.clobTokenIds) return
    let ids
    try {
      ids = typeof market.clobTokenIds === 'string' ? JSON.parse(market.clobTokenIds) : market.clobTokenIds
    } catch {
      return
    }
    const tokenId = Array.isArray(ids) ? ids[0] : null
    if (!tokenId) return
    let cancelled = false
    async function fetchHistory() {
      try {
        const res = await fetch(`/api/polymarket/prices-history?market=${encodeURIComponent(tokenId)}&interval=${chartInterval}`)
        if (cancelled) return
        if (!res.ok) return
        const data = await res.json()
        if (cancelled || !data?.history?.length) return
        setPriceHistory(data.history)
      } catch {
        setPriceHistory(null)
      }
    }
    fetchHistory()
    return () => { cancelled = true }
  }, [apiResponse, chartInterval])

  // Related markets: semantic search by title, top 3 results (excluding current market), then resolve CLOB token
  useEffect(() => {
    if (!apiResponse?.data) return
    const raw = apiResponse.data
    const events = Array.isArray(raw) ? raw : raw ? [raw] : []
    const event = events[0]
    const markets = event?.markets ?? []
    const currentMarketId = markets[0]?.id ? String(markets[0].id) : null
    const title = (event?.title ?? event?.question ?? apiResponse.slug ?? '').trim() || 'Market'
    let cancelled = false
    fetch('/api/search/semantic', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: title, num_tags: 5, events_per_tag: 30 }),
    })
      .then((r) => r.ok ? r.json() : { events: [] })
      .then(async (data) => {
        if (cancelled || !Array.isArray(data.events)) return
        const filtered = data.events
          .filter((ev) => ev?.best_market?.id && String(ev.best_market.id) !== currentMarketId)
          .slice(0, 3)
        const withTokens = []
        for (const ev of filtered) {
          const bm = ev.best_market
          const marketId = bm.id
          try {
            const res = await fetch(`/api/polymarket/markets/${encodeURIComponent(marketId)}`)
            if (cancelled || !res.ok) continue
            const marketData = await res.json()
            const cids = marketData?.clobTokenIds
            let tokenId = null
            if (Array.isArray(cids) && cids.length > 0) tokenId = cids[0]
            else if (typeof cids === 'string') try { const arr = JSON.parse(cids); tokenId = arr?.[0] } catch { /* ignore */ }
            if (tokenId) withTokens.push({ id: marketId, question: bm.question || ev.event_title || 'Market', tokenId })
          } catch { /* skip */ }
        }
        if (!cancelled) setRelatedCandidates(withTokens)
      })
      .catch(() => { if (!cancelled) setRelatedCandidates([]) })
    return () => { cancelled = true }
  }, [apiResponse])

  // Fetch price history for each selected related market (same interval as main)
  useEffect(() => {
    if (relatedCandidates.length === 0 || selectedRelatedIds.size === 0) {
      setRelatedHistories({})
      return
    }
    const toFetch = relatedCandidates.filter((c) => selectedRelatedIds.has(c.id))
    if (toFetch.length === 0) {
      setRelatedHistories({})
      return
    }
    let cancelled = false
    Promise.all(
      toFetch.map((c) =>
        fetch(`/api/polymarket/prices-history?market=${encodeURIComponent(c.tokenId)}&interval=${chartInterval}`)
          .then((r) => r.ok ? r.json() : { history: [] })
          .then((data) => ({ id: c.id, history: data?.history || [] }))
          .catch(() => ({ id: c.id, history: [] }))
      )
    ).then((results) => {
      if (cancelled) return
      const next = {}
      results.forEach(({ id, history }) => { next[id] = history })
      setRelatedHistories(next)
    })
    return () => { cancelled = true }
  }, [relatedCandidates, selectedRelatedIds, chartInterval])

  useEffect(() => {
    if (!apiResponse?.data) return
    const raw = apiResponse.data
    const events = Array.isArray(raw) ? raw : raw ? [raw] : []
    const event = events[0]
    const topic = (event?.title ?? event?.question ?? apiResponse.slug ?? 'Market').trim() || 'Market'
    let cancelled = false
    setDashboardNewsLoading(true)
    const searchUrl = `/api/nytimes/search?q=${encodeURIComponent(topic)}`
    fetch(searchUrl)
      .then((res) => res.ok ? res.json() : [])
      .then(async (data) => {
        if (cancelled) return
        if (Array.isArray(data) && data.length > 0) {
          setDashboardNews(data.slice(0, 4))
          return
        }
        const fallbackRes = await fetch('/api/nytimes/top-stories?section=home')
        const fallback = fallbackRes.ok ? await fallbackRes.json() : []
        if (!cancelled && Array.isArray(fallback)) setDashboardNews(fallback.slice(0, 4))
      })
      .catch(async () => {
        if (cancelled) return
        try {
          const fallbackRes = await fetch('/api/nytimes/top-stories?section=home')
          const fallback = fallbackRes.ok ? await fallbackRes.json() : []
          if (!cancelled && Array.isArray(fallback)) setDashboardNews(fallback.slice(0, 4))
        } catch {
          if (!cancelled) setDashboardNews([])
        }
      })
      .finally(() => { if (!cancelled) setDashboardNewsLoading(false) })
    return () => { cancelled = true }
  }, [apiResponse])

  if (loading) {
    return (
      <div className="min-h-screen bg-blue-50 flex items-center justify-center">
        <p className="text-black/60">Loading…</p>
      </div>
    )
  }
  if (error || !apiResponse) {
    return (
      <div className="min-h-screen bg-blue-50 flex flex-col items-center justify-center gap-4 px-4">
        <p className="text-black/80">{error ?? 'Not found'}</p>
        <button
          type="button"
          onClick={() => navigate('/')}
          className="bg-blue-700 text-white px-4 py-2"
        >
          Back to search
        </button>
      </div>
    )
  }

  const raw = apiResponse.data
  const events = Array.isArray(raw) ? raw : raw ? [raw] : []
  const event = events[0]
  const markets = event?.markets ?? events
  const title = event?.title ?? event?.question ?? apiResponse.slug ?? 'Market'
  const description = event?.description ?? null
  const image = event?.image ?? event?.icon
  const tags = event?.tags ?? []

  const primaryMarket = markets[0]
  const primaryPrice = primaryMarket?.lastTradePrice != null
    ? (primaryMarket.lastTradePrice * 100).toFixed(1)
    : (() => {
        const outcomes = primaryMarket ? parseOutcomes(primaryMarket) : []
        const yes = outcomes.find((o) => o.label === 'Yes')
        return yes?.price != null ? (yes.price * 100).toFixed(1) : null
      })()

  const { chartData, chartColor } = useMemo(() => {
    const now = primaryPrice != null ? Number(primaryPrice) : null
    if (priceHistory && priceHistory.length > 0) {
      const sorted = [...priceHistory].sort((a, b) => (a.t ?? 0) - (b.t ?? 0))
      const data = sorted.map(({ t, p }) => {
        const d = new Date((t ?? 0) * 1000)
        return {
          date: `${d.getMonth() + 1}/${d.getDate()}`,
          price: Math.round((p ?? 0) * 1000) / 10,
        }
      })
      const first = sorted[0]?.p
      const last = sorted[sorted.length - 1]?.p
      const isUp = last != null && first != null ? last > first : primaryMarket?.oneDayPriceChange != null ? primaryMarket.oneDayPriceChange >= 0 : true
      return {
        chartData: data,
        chartColor: isUp ? '#16a34a' : '#dc2626',
      }
    }
    // Fallback: synthetic data
    const points = 30
    const data = []
    const nowVal = now != null ? now : 2
    let p = Math.max(nowVal * 1.6, nowVal + 3)
    for (let i = 0; i < points; i++) {
      const t = new Date()
      t.setDate(t.getDate() - (points - 1 - i))
      const drift = (nowVal - p) / (points - i)
      const noise = (Math.random() - 0.5) * 1.2
      p = Math.max(0.1, p + drift + noise)
      data.push({
        date: `${t.getMonth() + 1}/${t.getDate()}`,
        price: Math.round(p * 10) / 10,
      })
    }
    data[data.length - 1].price = nowVal
    const isUp = primaryMarket?.oneDayPriceChange != null ? primaryMarket.oneDayPriceChange >= 0 : true
    return {
      chartData: data,
      chartColor: isUp ? '#16a34a' : '#dc2626',
    }
  }, [primaryPrice, priceHistory, primaryMarket?.oneDayPriceChange])

  // Merge related series into chart data; normalize each series to 0-100 so scales are comparable
  const { mergedChartData, relatedSeriesKeys, useNormalized } = useMemo(() => {
    const selectedRelated = relatedCandidates.filter((c) => selectedRelatedIds.has(c.id))
    const base = priceHistory && priceHistory.length > 0
      ? [...priceHistory].sort((a, b) => (a.t ?? 0) - (b.t ?? 0)).map(({ t, p }) => {
          const d = new Date((t ?? 0) * 1000)
          const raw = (p ?? 0) <= 1 ? (p ?? 0) * 100 : (p ?? 0)
          return { t: t ?? 0, date: `${d.getMonth() + 1}/${d.getDate()}`, price: raw }
        })
      : chartData?.map((row, i) => {
          const t = Math.floor(Date.now() / 1000) - (chartData.length - 1 - i) * 86400
          return { t, date: row.date, price: row.price }
        }) || []
    if (base.length === 0) return { mergedChartData: chartData || [], relatedSeriesKeys: [], useNormalized: false }
    const valueAtT = (history, t) => {
      if (!history?.length) return null
      let i = 0
      while (i < history.length && (history[i].t ?? 0) < t) i++
      if (i === 0) return history[0].p != null ? (history[0].p <= 1 ? history[0].p * 100 : history[0].p) : null
      if (i >= history.length) return history[history.length - 1].p != null ? (history[history.length - 1].p <= 1 ? history[history.length - 1].p * 100 : history[history.length - 1].p) : null
      const a = history[i - 1]
      const b = history[i]
      const pa = a.p != null ? (a.p <= 1 ? a.p * 100 : a.p) : null
      const pb = b.p != null ? (b.p <= 1 ? b.p * 100 : b.p) : null
      if (pa == null) return pb
      if (pb == null) return pa
      const ta = a.t ?? 0
      const tb = b.t ?? 0
      if (tb === ta) return pa
      const frac = (t - ta) / (tb - ta)
      return pa + frac * (pb - pa)
    }
    const series = { main: base.map((r) => r.price) }
    selectedRelated.forEach((c, idx) => {
      const hist = relatedHistories[c.id] || []
      series[`rel_${c.id}`] = base.map((r) => valueAtT(hist, r.t))
    })
    const keys = ['main', ...selectedRelated.map((c) => `rel_${c.id}`)]
    const mins = {}
    const maxs = {}
    keys.forEach((k) => {
      const vals = series[k].filter((v) => v != null && !Number.isNaN(v))
      if (vals.length === 0) { mins[k] = 0; maxs[k] = 100 } else { mins[k] = Math.min(...vals); maxs[k] = Math.max(...vals) }
    })
    const norm = (k, v) => {
      if (v == null || Number.isNaN(v)) return null
      const min = mins[k]
      const max = maxs[k]
      if (max === min) return 50
      return ((v - min) / (max - min)) * 100
    }
    const mergedData = base.map((row, i) => {
      const out = { date: row.date, price: selectedRelated.length > 0 ? norm('main', row.price) : row.price }
      selectedRelated.forEach((c) => {
        const key = `rel_${c.id}`
        out[key] = norm(key, series[key][i])
      })
      return out
    })
    const relatedSeriesKeys = selectedRelated.map((c) => ({ id: c.id, key: `rel_${c.id}`, question: c.question }))
    return { mergedChartData: mergedData, relatedSeriesKeys, useNormalized: selectedRelated.length > 0 }
  }, [priceHistory, chartData, relatedHistories, selectedRelatedIds, relatedCandidates])

  const toggleRelated = (id) => {
    setSelectedRelatedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <div className="min-h-screen bg-blue-50 text-black flex flex-col">
      <BlueSwipe />
      {/* Header — dashboard: solid blue-700 */}
      <header className="sticky top-0 z-50 bg-blue-700">
        <nav className="flex h-20 items-center justify-between px-4 md:px-6">
          <a href="/" className="flex items-center gap-2 shrink-0">
            <span className="flex h-8 w-8 items-center justify-center bg-white/20 font-bold text-white text-sm">PA</span>
            <span className="hidden font-semibold tracking-tight text-white sm:inline">Polymarket Arb</span>
          </a>
          <div className="flex items-center gap-6">
            <ul className="hidden gap-6 md:flex">
              <li><a href="/" className="text-sm text-white hover:text-white/80">Home</a></li>
              <li><a href="/markets" className="text-sm text-white hover:text-white/80">Markets</a></li>
              <li><a href="/strategies" className="text-sm text-white hover:text-white/80">Strategies</a></li>
              <li><a href="/arb" className="text-sm text-white hover:text-white/80">Arbitrage</a></li>
            </ul>
            <form className="w-full max-w-[200px] md:max-w-[240px]" onSubmit={handleNavSearchSubmit}>
              <div className="group relative flex w-full items-center rounded pl-2.5 pr-2.5">
                <div
                  className="pointer-events-none absolute inset-0 z-0 rounded"
                  style={{
                    background: 'linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.12) 10%, rgba(255,255,255,0.25) 22%, rgba(255,255,255,0.25) 78%, rgba(255,255,255,0.12) 90%, transparent 100%)',
                  }}
                />
                <div className="pointer-events-none absolute inset-0 z-0 rounded bg-white/50 opacity-0 transition-opacity duration-300 group-focus-within:opacity-100" />
                <span className="relative z-10 mr-2 flex shrink-0 text-white/90" aria-hidden>
                  <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                  </svg>
                </span>
                <input
                  type="search"
                  placeholder="New search…"
                  aria-label="New search"
                  className="relative z-10 w-full border-0 bg-transparent py-2 pl-0 pr-1 text-sm text-white placeholder-white/60 outline-none"
                  value={navSearchValue}
                  onChange={(e) => setNavSearchValue(e.target.value)}
                />
              </div>
            </form>
          </div>
        </nav>
      </header>

      {/* Two-column layout */}
      <div className="flex flex-1 flex-col lg:flex-row">
        {/* LEFT COLUMN */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* Interactive chart — 80vh with generous padding, extra top space */}
          <div className="pt-20 pb-10 px-10 md:pt-24 md:pb-12 md:px-12 flex flex-col" style={{ height: '80vh' }}>
            <div className="flex justify-end mb-2">
              <div className="inline-flex" role="tablist" aria-label="Chart time range">
                {[
                  { value: '1d', label: '1D' },
                  { value: '1w', label: '1W' },
                  { value: 'max', label: '1M' },
                ].map(({ value, label }) => {
                  const selected = chartInterval === value
                  return (
                    <button
                      key={value}
                      type="button"
                      role="tab"
                      aria-selected={selected}
                      onClick={() => setChartInterval(value)}
                      className={`group relative px-4 py-2 text-sm font-medium overflow-hidden ${
                        selected ? 'bg-blue-700 text-white' : 'bg-transparent text-black'
                      }`}
                    >
                      {!selected && (
                        <>
                          <span className="absolute left-0 top-0 bottom-0 w-0 bg-blue-700 group-hover:w-1/2 transition-[width] duration-300 ease-out pointer-events-none" aria-hidden />
                          <span className="absolute right-0 top-0 bottom-0 w-0 bg-blue-700 group-hover:w-1/2 transition-[width] duration-300 ease-out pointer-events-none" aria-hidden />
                        </>
                      )}
                      <span className="relative z-10 group-hover:text-white transition-colors duration-300">{label}</span>
                    </button>
                  )
                })}
              </div>
            </div>
            <div className="flex-1 min-h-0">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={useNormalized ? mergedChartData : chartData} margin={{ top: 12, right: 16, bottom: 8, left: 8 }}>
                  <defs>
                    <linearGradient id="chartGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={chartColor} stopOpacity={0.35} />
                      <stop offset="100%" stopColor={chartColor} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" vertical={false} />
                  <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#999' }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 10, fill: '#999' }} axisLine={false} tickLine={false} tickFormatter={(v) => useNormalized ? `${Number(v).toFixed(1).replace(/\.?0+$/, '')}%` : `${Number(v).toFixed(3).replace(/\.?0+$/, '')}¢`} domain={useNormalized ? [0, 100] : ['dataMin - 0.5', 'dataMax + 0.5']} />
                  <Tooltip
                    contentStyle={{ fontSize: 12, border: '1px solid #e5e7eb', boxShadow: 'none' }}
                    formatter={(v, name) => [v != null ? (useNormalized ? `${Number(v).toFixed(1)}%` : `${Number(v).toFixed(1)}¢`) : '—', name === 'price' ? 'This market' : relatedSeriesKeys.find((r) => r.key === name)?.question || name]}
                    labelStyle={{ fontSize: 11, color: '#666' }}
                  />
                  <Area type="monotone" dataKey="price" name="This market" stroke={chartColor} strokeWidth={1.5} fill="url(#chartGrad)" dot={false} activeDot={{ r: 3, fill: chartColor }} />
                  {relatedSeriesKeys.map((r, i) => {
                    const colors = ['#2563eb', '#7c3aed', '#059669', '#dc2626']
                    const stroke = colors[i % colors.length]
                    return <Line key={r.key} type="monotone" dataKey={r.key} name={r.question} stroke={stroke} strokeWidth={1.5} dot={false} activeDot={{ r: 3, fill: stroke }} />
                  })}
                </ComposedChart>
              </ResponsiveContainer>
            </div>
            {/* Related markets: top 4 as checkbox-style toggles, blue slide on hover, blue when selected */}
            {relatedCandidates.length > 0 && (
              <div className="mt-4 flex flex-wrap items-center gap-2">
                <span className="text-sm text-black/60 mr-1">Compare:</span>
                {relatedCandidates.map((c) => {
                  const selected = selectedRelatedIds.has(c.id)
                  return (
                    <button
                      key={c.id}
                      type="button"
                      onClick={() => toggleRelated(c.id)}
                      className={`group relative overflow-hidden px-3 py-1.5 text-left text-sm max-w-[220px] truncate ${
                        selected ? 'bg-blue-700 text-white' : 'bg-transparent text-black'
                      }`}
                      title={c.question}
                    >
                      {!selected && (
                        <>
                          <span className="absolute left-0 top-0 bottom-0 w-0 bg-blue-700 group-hover:w-1/2 transition-[width] duration-300 ease-out pointer-events-none" aria-hidden />
                          <span className="absolute right-0 top-0 bottom-0 w-0 bg-blue-700 group-hover:w-1/2 transition-[width] duration-300 ease-out pointer-events-none" aria-hidden />
                        </>
                      )}
                      <span className="relative z-10 group-hover:text-white transition-colors duration-300">{c.question}</span>
                    </button>
                  )
                })}
              </div>
            )}
          </div>

          {/* News — NY Times API */}
          <div className="pt-6">
            <h3 className="px-6 pb-4 text-2xl font-semibold text-black">News</h3>
            {dashboardNewsLoading ? (
              <p className="px-6 py-4 text-black/50 text-sm">Loading news…</p>
            ) : dashboardNews.length === 0 ? (
              <p className="px-6 py-4 text-black/50 text-sm">No news available.</p>
            ) : (
              <ul>
                {dashboardNews.map((article) => (
                  <li key={article.id} className="border-t border-black/10">
                    <a
                      href={article.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center gap-4 px-6 py-4 hover:bg-black/5 transition-colors"
                    >
                      {article.image_url ? (
                        <img src={article.image_url} alt="" className="h-20 w-20 shrink-0 object-cover" />
                      ) : (
                        <div className="h-20 w-20 shrink-0 bg-gray-200 flex items-center justify-center">
                          <span className="text-gray-400 text-xs">No image</span>
                        </div>
                      )}
                      <div className="min-w-0 flex-1">
                        <span className="text-base text-black">{article.title}</span>
                      </div>
                      <span className="text-sm text-black/50 shrink-0">The New York Times</span>
                    </a>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        {/* RIGHT COLUMN — blue-700 bg, white text */}
        <div className="w-full lg:w-[420px] flex flex-col shrink-0 bg-blue-700 text-white">
          {/* Price + event image square */}
          <div className="px-8 py-5 flex items-center justify-between gap-4">
            <div>
              <h3 className="text-base font-medium italic text-white mb-2">Price</h3>
              <p className="text-4xl font-bold text-white">
                {primaryPrice != null ? `${primaryPrice}¢` : '—'}
              </p>
              {primaryMarket?.oneDayPriceChange != null && (
                <p className={`mt-1 text-base ${primaryMarket.oneDayPriceChange >= 0 ? 'text-green-200' : 'text-red-200'}`}>
                  {primaryMarket.oneDayPriceChange >= 0 ? '+' : ''}{(primaryMarket.oneDayPriceChange * 100).toFixed(2)}% 24h
                </p>
              )}
            </div>
            {image && (
              <div className="shrink-0 h-20 w-20 overflow-hidden rounded">
                <img src={image} alt="" className="h-full w-full object-cover" />
              </div>
            )}
          </div>

          {/* Vol | Liquidity */}
          <div className="grid grid-cols-2 border-t border-white/20">
            <div className="px-8 py-4 border-r border-white/20">
              <p className="text-sm text-white/70 mb-1">Vol</p>
              <p className="font-semibold text-white text-base">
                ${Number(event?.volume ?? event?.volumeNum ?? 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}
              </p>
            </div>
            <div className="px-8 py-4">
              <p className="text-sm text-white/70 mb-1">Liquidity</p>
              <p className="font-semibold text-white text-base">
                ${Number(event?.liquidity ?? event?.liquidityNum ?? 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}
              </p>
            </div>
          </div>

          {/* Context by polymarket */}
          <div className="border-t border-white/20 px-8 py-4">
            <h3 className="text-base font-medium italic text-white mb-2">Context by polymarket</h3>
            {description ? (
              <div className="whitespace-pre-wrap text-sm text-white/90 leading-relaxed">
                {description}
              </div>
            ) : (
              <p className="text-sm text-white/60">No description available.</p>
            )}
          </div>

          {/* Relevant bills */}
          <div className="border-t border-white/20 px-8 py-4">
            <h3 className="text-base font-medium italic text-white mb-2">Relevant bills</h3>
            <ul className="space-y-2">
              <li className="text-sm text-white/90">H.R. 3684 — Foreign Acquisition Review Act, expanding CFIUS oversight of foreign-linked purchases of U.S. and EU carriers</li>
              <li className="text-sm text-white/90">S. 1029 — Aviation Competition Preservation Act, restricting cross-industry conglomerate ownership of commercial airlines</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  )
}

function Spinner() {
  return (
    <svg className="step-spinner h-5 w-5 text-blue-600" viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeDasharray="31.4 31.4" />
    </svg>
  )
}

function SemanticResultsPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const prompt = location.state?.prompt ?? null
  const pipelineRef = useRef(null)

  const [matchedTags, setMatchedTags] = useState(null)
  const [tagBreakdowns, setTagBreakdowns] = useState({})
  const [activeTagIdx, setActiveTagIdx] = useState(-1)
  const [wordMarkets, setWordMarkets] = useState(null)
  const [pipelinePhase, setPipelinePhase] = useState('idle')
  const [expandedTags, setExpandedTags] = useState({})
  const [error, setError] = useState(null)
  const [timings, setTimings] = useState({})
  const [resultsCollapsed, setResultsCollapsed] = useState(false)
  const [basketData, setBasketData] = useState(null)
  const [basketLoading, setBasketLoading] = useState(false)
  const [basketError, setBasketError] = useState(null)
  const [hoveredWeightIndex, setHoveredWeightIndex] = useState(null)
  const [navSearchValue, setNavSearchValue] = useState('')

  function handleNavSearchSubmit(e) {
    e.preventDefault()
    const input = navSearchValue.trim()
    if (!input) return
    navigate('/search', { state: { prompt: input } })
  }

  useEffect(() => {
    if (!prompt) return
    setBasketData(null)
    setBasketError(null)
    let cancelled = false

    async function runPipeline() {
      setPipelinePhase('matching_tags')
      const t0 = performance.now()
      try {
        const res = await fetch('/api/search/semantic/match-tags', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ prompt, num_tags: 5 }),
        })
        if (cancelled) return
        const data = await res.json()
        if (!res.ok) throw new Error(data?.detail ?? 'Tag matching failed')
        setMatchedTags(data.matched_tags ?? [])
        setTimings((t) => ({ ...t, tags: Math.round(performance.now() - t0) }))
      } catch (e) {
        if (!cancelled) setError(e.message)
        return
      }

      if (cancelled) return
      setPipelinePhase('fetching_events')

      const tagsSnapshot = await new Promise((resolve) => {
        setMatchedTags((prev) => { resolve(prev); return prev })
      })
      for (let i = 0; i < tagsSnapshot.length; i++) {
        if (cancelled) return
        const tag = tagsSnapshot[i]
        setActiveTagIdx(i)
        const t1 = performance.now()
        try {
          const res = await fetch('/api/search/semantic/tag-events', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tag_slug: tag.slug, tag_label: tag.label, tag_score: tag.score, events_per_tag: 30 }),
          })
          if (cancelled) return
          const data = await res.json()
          const elapsed = Math.round(performance.now() - t1)
          if (res.ok) {
            setTagBreakdowns((prev) => ({ ...prev, [tag.slug]: { ...data, _elapsed: elapsed } }))
            setExpandedTags((prev) => ({ ...prev, [tag.slug]: true }))
          } else {
            setTagBreakdowns((prev) => ({ ...prev, [tag.slug]: { error: data?.detail ?? 'Failed', _elapsed: elapsed } }))
          }
        } catch (e) {
          if (!cancelled) setTagBreakdowns((prev) => ({ ...prev, [tag.slug]: { error: e.message } }))
        }
      }

      if (cancelled) return
      setActiveTagIdx(-1)
      setPipelinePhase('word_search')

      const t2 = performance.now()
      try {
        const res = await fetch('/api/search/semantic/word-search', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ prompt }),
        })
        if (cancelled) return
        const data = await res.json()
        setWordMarkets(res.ok ? (data.markets ?? []) : [])
        setTimings((t) => ({ ...t, wordSearch: Math.round(performance.now() - t2) }))
      } catch {
        if (!cancelled) setWordMarkets([])
        setTimings((t) => ({ ...t, wordSearch: Math.round(performance.now() - t2) }))
      }

      if (!cancelled) setPipelinePhase('complete')
    }

    runPipeline()
    return () => { cancelled = true }
  }, [prompt])

  // Scroll results into view as pipeline progresses or completes
  useEffect(() => {
    if (pipelinePhase === 'idle' || !prompt) return
    const el = pipelineRef.current
    if (el) {
      const t = setTimeout(() => el.scrollIntoView({ behavior: 'smooth', block: 'nearest' }), 100)
      return () => clearTimeout(t)
    }
  }, [pipelinePhase, activeTagIdx, prompt])

  // Collapse pipeline section when complete
  useEffect(() => {
    if (pipelinePhase === 'complete') setResultsCollapsed(true)
  }, [pipelinePhase])

  // After pipeline complete: fetch full semantic (events with best_market), then basket if text match > 70%
  useEffect(() => {
    if (pipelinePhase !== 'complete' || !prompt) return
    let cancelled = false
    setBasketLoading(true)
    setBasketError(null)

    async function fetchBasket() {
      try {
        const res = await fetch('/api/search/semantic', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ prompt, num_tags: 5, events_per_tag: 30 }),
        })
        if (cancelled) return
        const data = await res.json()
        if (!res.ok) {
          setBasketError(data?.detail ?? 'Semantic search failed')
          setBasketLoading(false)
          return
        }
        const wordSearchMarkets = data.word_search_markets ?? []
        const events = data.events ?? []
        const best = wordSearchMarkets.length
          ? wordSearchMarkets.reduce((a, b) => ((b.score ?? 0) > (a.score ?? 0) ? b : a), wordSearchMarkets[0])
          : null
        const hasStrongTarget = best && (best.score ?? 0) > 0.7
        const allInputIds = events.map((e) => e.best_market?.id).filter(Boolean)
        const uniqueInputIds = [...new Set(allInputIds)].slice(0, 15)
        if (uniqueInputIds.length === 0) {
          setBasketLoading(false)
          return
        }
        if (!hasStrongTarget) {
          const basketRes = await fetch('/api/basket-no-target', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              input_market_ids: uniqueInputIds,
              top_k: 10,
            }),
          })
          if (cancelled) return
          const basketJson = await basketRes.json()
          if (!basketRes.ok) {
            setBasketError(basketJson?.detail ?? 'Basket failed')
            setBasketLoading(false)
            return
          }
          setBasketData({
            ...basketJson,
            noTarget: true,
            target_question: basketJson.centroid_question ?? 'Synthetic basket (no single target)',
          })
        } else {
        // Use only best_market.id (same source as inputs) — match word-search best to an event’s best_market
        // best.id is same field as best_market.id (backend resolves word-search ids via Gamma)
          const targetMarketId = best.id
          const excludeIds = new Set([targetMarketId, ...wordSearchMarkets.map((m) => m.id)])
          const inputIds = uniqueInputIds.filter((id) => !excludeIds.has(id)).slice(0, 10)
          if (inputIds.length === 0) {
            setBasketLoading(false)
            return
          }
          const basketRes = await fetch('/api/basket', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              target_market_id: targetMarketId,
              input_market_ids: inputIds,
              days: 7,
            }),
          })
          if (cancelled) return
          const basketJson = await basketRes.json()
          if (!basketRes.ok) {
            setBasketError(basketJson?.detail ?? 'Basket failed')
            setBasketLoading(false)
            return
          }
          setBasketData(basketJson)
        }
      } catch (e) {
        if (!cancelled) {
          setBasketError(e.message ?? 'Request failed')
        }
      } finally {
        if (!cancelled) setBasketLoading(false)
      }
    }
    fetchBasket()
    return () => { cancelled = true }
  }, [pipelinePhase, prompt])

  if (!prompt) {
    return (
      <div className="min-h-screen bg-blue-50 flex flex-col items-center justify-center gap-4 px-4">
        <p className="text-lg text-black/60">No search prompt.</p>
        <button type="button" onClick={() => navigate('/')} className="text-blue-700 text-base underline underline-offset-2">Back to search</button>
      </div>
    )
  }

  const step2Done = ['word_search', 'complete'].includes(pipelinePhase)
  const totalEvents = Object.values(tagBreakdowns).reduce((sum, tb) => sum + (tb.events_count ?? 0), 0)

  function toggleTag(slug) {
    setExpandedTags((prev) => ({ ...prev, [slug]: !prev[slug] }))
  }

  return (
    <div className="min-h-screen bg-blue-50 text-black flex flex-col">
      <BlueSwipe />
      <header className="sticky top-0 z-50 pb-12 bg-[linear-gradient(to_bottom,rgb(29_78_216)_0%,rgb(37_99_235)_35%,rgb(59_130_246)_50%,rgb(147_197_253)_65%,rgb(219_234_254)_80%,rgb(239_246_255)_100%)]">
        <nav className="flex h-20 items-center justify-between px-4 md:px-6">
          <a href="/" className="flex items-center gap-2 shrink-0">
            <span className="flex h-8 w-8 items-center justify-center bg-white/20 font-bold text-white text-sm">PA</span>
            <span className="hidden font-semibold tracking-tight text-white sm:inline">Polymarket Arb</span>
          </a>
          <form className="w-full max-w-[200px] md:max-w-[240px]" onSubmit={handleNavSearchSubmit}>
            <div className="group relative flex w-full items-center rounded pl-2.5 pr-2.5">
              <div
                className="pointer-events-none absolute inset-0 z-0 rounded"
                style={{
                  background: 'linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.12) 10%, rgba(255,255,255,0.25) 22%, rgba(255,255,255,0.25) 78%, rgba(255,255,255,0.12) 90%, transparent 100%)',
                }}
              />
              <div className="pointer-events-none absolute inset-0 z-0 rounded bg-white/50 opacity-0 transition-opacity duration-300 group-focus-within:opacity-100" />
              <span className="relative z-10 mr-2 flex shrink-0 text-white/90" aria-hidden>
                <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                </svg>
              </span>
              <input
                type="search"
                placeholder="New search…"
                aria-label="New search"
                className="relative z-10 w-full border-0 bg-transparent py-2 pl-0 pr-1 text-sm text-white placeholder-white/60 outline-none"
                value={navSearchValue}
                onChange={(e) => setNavSearchValue(e.target.value)}
              />
            </div>
          </form>
        </nav>
      </header>

      <div className="mx-auto w-full max-w-7xl px-6 md:px-10 pt-14 pb-24">
        <div className="flex items-center justify-between gap-4 mb-2">
          <h1 className="text-3xl font-medium tracking-tight text-black/80 min-w-0">"{prompt}"</h1>
          <a
            href="/search/graph"
            onClick={(e) => { e.preventDefault(); navigate('/search/graph', { state: { prompt } }) }}
            className="group hover:text-white relative shrink-0 overflow-hidden rounded px-3 py-1.5 text-sm text-gray-500 no-underline transition-colors duration-300 group-hover:text-white"
          >
            <span className="absolute inset-y-0 left-0 w-0 bg-blue-700 transition-[width] duration-300 ease-out group-hover:w-full" aria-hidden />
            <span className="relative z-10">Perform graph analysis</span>
          </a>
        </div>
        <div className="h-px bg-black/10 mb-12" />

        {error && (
          <p className="step-appear text-base text-red-600 mb-8">{error}</p>
        )}

        {/* Thinking process: collapsible when complete */}
        <div ref={pipelineRef}>
          {pipelinePhase === 'complete' && (
            <button
              type="button"
              onClick={() => setResultsCollapsed((c) => !c)}
              className="w-full flex items-center justify-between gap-4 py-2 text-left"
            >
              <span className="text-sm text-black/70 truncate">
                <span className="font-medium text-black">"{prompt}"</span>
                {' — '}
                <span className="text-black/50">{matchedTags?.length ?? 0} tags</span>
                {' · '}
                <span className="text-black/50">{totalEvents} events</span>
                {' · '}
                <span className="text-black/50">{wordMarkets?.length ?? 0} text matches</span>
              </span>
              <svg
                className={`h-5 w-5 shrink-0 text-black/40 transition-transform duration-200 ${resultsCollapsed ? '' : 'rotate-180'}`}
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>
          )}
          {(!resultsCollapsed || pipelinePhase !== 'complete') && (
            <div className="relative pl-8">
              <div className="absolute left-0 top-1 bottom-0 w-px bg-black/10" />

          {/* STEP 1 — Match tags */}
          <div className="relative mb-12">
            <div className="absolute -left-8 top-1 w-4 h-4 rounded-full border-2 border-blue-50 transition-colors duration-300"
              style={{ backgroundColor: matchedTags ? '#16a34a' : pipelinePhase === 'matching_tags' ? '#2563eb' : '#d1d5db' }} />

            <div className="flex items-center gap-3 mb-2">
              <span className="text-sm font-medium text-black/40 uppercase tracking-wider">Matching tags</span>
              {pipelinePhase === 'matching_tags' && <Spinner />}
              {timings.tags != null && <span className="text-sm text-black/20 font-mono">{timings.tags}ms</span>}
            </div>

            {matchedTags && (
              <div className="step-appear mt-4">
                <p className="text-lg text-black/50 mb-4">
                  Found <span className="font-semibold text-black">{matchedTags.length}</span> tags by embedding similarity
                </p>
                {matchedTags.map((tag, i) => (
                  <div key={tag.slug} className="step-appear flex items-center gap-4 py-2.5" style={{ animationDelay: `${i * 60}ms` }}>
                    <span className="text-sm font-mono text-black/20 w-4 text-right shrink-0">{i + 1}</span>
                    <span className="text-base text-black/80 flex-1 truncate">{tag.label}</span>
                    <div className="shrink-0 flex items-center gap-3">
                      <div className="w-24 h-1.5 bg-black/5 overflow-hidden rounded-full">
                        <div className="h-full bg-blue-600 rounded-full score-bar-fill" style={{ '--target-width': `${Math.max(tag.score * 100, 3)}%` }} />
                      </div>
                      <span className="text-sm font-mono text-blue-600 w-14 text-right">{(tag.score * 100).toFixed(1)}%</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* STEP 2 — Events per tag */}
          {matchedTags && (
            <div className="relative mb-12 step-appear">
              <div className="absolute -left-8 top-1 w-4 h-4 rounded-full border-2 border-blue-50 transition-colors duration-300"
                style={{ backgroundColor: step2Done ? '#16a34a' : pipelinePhase === 'fetching_events' ? '#2563eb' : '#d1d5db' }} />

              <div className="flex items-center gap-3 mb-5">
                <span className="text-sm font-medium text-black/40 uppercase tracking-wider">Fetching events per tag</span>
                {pipelinePhase === 'fetching_events' && <Spinner />}
              </div>

              {matchedTags.map((tag, i) => {
                const bd = tagBreakdowns[tag.slug]
                const isLoading = pipelinePhase === 'fetching_events' && activeTagIdx === i && !bd
                const isExpanded = expandedTags[tag.slug]
                const isVisible = bd || isLoading || (pipelinePhase === 'fetching_events' && activeTagIdx >= i)

                if (!isVisible) return null

                return (
                  <div key={tag.slug} className="step-appear mb-1">
                    <button
                      type="button"
                      onClick={() => bd && toggleTag(tag.slug)}
                      className="w-full flex items-center gap-3 py-3 text-left group"
                    >
                      {isLoading ? (
                        <Spinner />
                      ) : bd ? (
                        <svg className={`h-4 w-4 shrink-0 text-black/25 transition-transform duration-200 ${isExpanded ? 'rotate-90' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M9 5l7 7-7 7" />
                        </svg>
                      ) : (
                        <div className="h-4 w-4 shrink-0" />
                      )}
                      <span className="text-base text-black/70 group-hover:text-black transition-colors truncate">{tag.label}</span>
                      <span className="text-sm font-mono text-black/20 ml-auto shrink-0">
                        {bd && !bd.error ? `${bd.events_count} events` : bd?.error ? 'failed' : ''}
                      </span>
                      {bd?._elapsed != null && (
                        <span className="text-sm font-mono text-black/15 shrink-0">{bd._elapsed}ms</span>
                      )}
                    </button>

                    {isExpanded && bd && !bd.error && (
                      <div className="step-appear pl-7 pb-4">
                        <div className="flex gap-8 text-sm text-black/40 mb-3">
                          <span><span className="font-semibold text-black/70">{bd.events_count}</span> events</span>
                          <span><span className="font-semibold text-black/70">{bd.total_markets}</span> markets</span>
                          <span><span className="font-semibold text-black/70">{bd.avg_markets_per_event?.toFixed(1) ?? '—'}</span> avg/event</span>
                        </div>
                        {bd.event_titles?.length > 0 && (
                          <div className="border-l border-black/8 pl-4">
                            {bd.event_titles.map((title, idx) => (
                              <p key={idx} className="text-sm text-black/50 py-1 leading-relaxed">
                                <span className="font-mono text-black/20 mr-2">{idx + 1}.</span>{title}
                              </p>
                            ))}
                          </div>
                        )}
                      </div>
                    )}

                    {i < matchedTags.length - 1 && bd && <div className="h-px bg-black/5 ml-7" />}
                  </div>
                )
              })}
            </div>
          )}

          {/* STEP 3 — Word search */}
          {(pipelinePhase === 'word_search' || pipelinePhase === 'complete') && (
            <div className="relative mb-12 step-appear">
              <div className="absolute -left-8 top-1 w-4 h-4 rounded-full border-2 border-blue-50 transition-colors duration-300"
                style={{ backgroundColor: pipelinePhase === 'complete' ? '#16a34a' : '#2563eb' }} />

              <div className="flex items-center gap-3 mb-2">
                <span className="text-sm font-medium text-black/40 uppercase tracking-wider">Word search</span>
                {pipelinePhase === 'word_search' && <Spinner />}
                {timings.wordSearch != null && <span className="text-sm text-black/20 font-mono">{timings.wordSearch}ms</span>}
              </div>

              {wordMarkets && (
                <div className="step-appear mt-4">
                  <p className="text-lg text-black/50 mb-4">
                    <span className="font-semibold text-black">{wordMarkets.length}</span> text match{wordMarkets.length !== 1 ? 'es' : ''}
                  </p>
                  {wordMarkets.map((wm, i) => (
                    <div key={wm.id} className="step-appear py-3" style={{ animationDelay: `${i * 50}ms` }}>
                      <div className="flex items-start justify-between gap-6">
                        <p className="text-base text-black/70 leading-relaxed">{wm.question}</p>
                        {wm.score != null && (
                          <span className="shrink-0 text-sm font-mono text-blue-600">{(wm.score * 100).toFixed(1)}%</span>
                        )}
                      </div>
                      {i < wordMarkets.length - 1 && <div className="h-px bg-black/5 mt-3" />}
                    </div>
                  ))}
                  {wordMarkets.length === 0 && (
                    <p className="text-base text-black/30">No keyword matches.</p>
                  )}
                </div>
              )}
            </div>
          )}

          {/* DONE */}
          {pipelinePhase === 'complete' && (
            <div className="relative step-appear">
              <div className="absolute -left-8 top-1 w-4 h-4 rounded-full bg-green-600 border-2 border-blue-50" />
              <div className="h-px bg-black/10 mb-5" />
              <p className="text-sm text-black/30">
                Done — <span className="text-black/50">{matchedTags?.length ?? 0} tags</span>
                {' · '}<span className="text-black/50">{totalEvents} events</span>
                {' · '}<span className="text-black/50">{wordMarkets?.length ?? 0} text matches</span>
              </p>
            </div>
          )}
            </div>
          )}
        </div>

        {/* Full-width section below: no side margins; graph slightly in from left, heatmap right */}
        <div className="w-screen relative left-1/2 -ml-[50vw] mt-12">
          <section
            className="results-section-resize w-full overflow-hidden"
            style={{ minHeight: (basketData || basketLoading || basketError) ? 440 : 0 }}
          >
            <div className="flex flex-col md:flex-row gap-6 w-full min-h-[440px] transition-all duration-300 ease-out pl-10 pr-0">
              {/* Left subsection: graph — 70% width */}
              <div className="results-subsection-resize flex-[0_0_70%] min-w-0 flex flex-col items-start overflow-hidden">
                <h2 className="text-base font-medium text-black/50 uppercase tracking-wider mb-4">
                  Target vs synthetic
                </h2>
              <div className="w-full min-h-[440px] flex flex-col items-center justify-center transition-all duration-300 ease-out">
                {basketLoading && (
                  <p className="text-base text-black/50 flex items-center gap-2">
                    <Spinner />
                    Loading basket and time series…
                  </p>
                )}
                {!basketLoading && basketError && (
                  <p className="text-base text-red-600">{basketError}</p>
                )}
                {!basketLoading && !basketError && !basketData && (
                  <p className="text-base text-black/50 text-center max-w-md">
                    If a search returns a strong text match (&gt;70%), the target market and synthetic basket time series will appear here.
                  </p>
                )}
                {!basketLoading && !basketError && basketData && (() => {
                  if (basketData.noTarget) {
                    return (
                      <div className="w-full flex flex-col items-start transition-all duration-300 ease-out">
                        <p className="text-base text-black/60 mb-2 truncate max-w-full" title={basketData.target_question}>
                          {basketData.target_question}
                        </p>
                        <p className="text-sm text-black/40 mb-3">
                          No single target market matched strongly; basket built from semantic similarity. Weights below.
                        </p>
                      </div>
                    )
                  }
                  const ts = basketData.timestamps ?? []
                  const targetPrices = basketData.target_prices ?? []
                  const syntheticPrices = basketData.synthetic_prices ?? []
                  const chartData = ts.map((t, i) => {
                    const d = new Date(t)
                    return {
                      date: `${d.getMonth() + 1}/${d.getDate()}`,
                      target: Math.round((targetPrices[i] ?? 0) * 1000) / 10,
                      synthetic: Math.round((syntheticPrices[i] ?? 0) * 1000) / 10,
                    }
                  })
                  return (
                    <div className="w-full flex flex-col items-start transition-all duration-300 ease-out">
                      <p className="text-base text-black/60 mb-2 truncate max-w-full" title={basketData.target_question}>
                        {basketData.target_question}
                      </p>
                      {basketData.r_squared != null && (
                        <p className="text-sm text-black/40 mb-3">R² = {Number(basketData.r_squared).toFixed(4)}</p>
                      )}
                      <div className="w-full h-[420px] transition-all duration-300 ease-out">
                        <ResponsiveContainer width="100%" height="100%">
                          <LineChart data={chartData} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                            <XAxis dataKey="date" tick={{ fontSize: 13 }} stroke="#9ca3af" />
                            <YAxis domain={[0, 100]} tick={{ fontSize: 13 }} stroke="#9ca3af" tickFormatter={(v) => `${v}%`} />
                            <Tooltip formatter={(v) => `${Number(v).toFixed(1)}%`} labelFormatter={(l) => l} />
                            <Line type="monotone" dataKey="target" name="Target" stroke="#2563eb" strokeWidth={2} dot={false} />
                            <Line type="monotone" dataKey="synthetic" name="Synthetic" stroke="#16a34a" strokeWidth={2} dot={false} />
                          </LineChart>
                        </ResponsiveContainer>
                      </div>
                    </div>
                  )
                })()}
              </div>
            </div>

            {/* Right subsection: heatmap — 30% width, with resize transitions */}
            <div className="results-subsection-resize flex-1 min-w-0 flex flex-col overflow-hidden transition-all duration-300 ease-out">
              {!basketLoading && !basketError && basketData?.weights?.length > 0 && (() => {
                const weights = basketData.weights
                const totalAbs = weights.reduce((s, w) => s + Math.abs(Number(w.weight)), 0) || 1
                const pcts = weights.map((w) => (Math.abs(Number(w.weight)) / totalAbs) * 100)
                const maxPct = Math.max(...pcts, 1)
                const firstThree = (title) => {
                  const words = (title || '').trim().split(/\s+/)
                  return words.slice(0, 3).join(' ')
                }
                return (
                  <>
                    <h2 className="text-base font-medium text-black/50 uppercase tracking-wider mb-3">
                      Basket weights
                    </h2>
                    <div
                      className="heatmap-grid-resize grid gap-0 w-full flex-1 min-h-0 transition-all duration-300 ease-out"
                      style={{
                        gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))',
                      }}
                    >
                      {weights.map((w, i) => {
                        const intensity = maxPct > 0 ? pcts[i] / maxPct : 0
                        const isHovered = hoveredWeightIndex === i
                        const mild = `rgba(37, 99, 235, ${0.2 + intensity * 0.5})`
                        const strong = `rgba(29, 78, 216, ${0.5 + intensity * 0.45})`
                        const fill = isHovered ? strong : mild
                        // Circle size proportional to weight: ~28% to ~70% of cell
                        const sizePct = 28 + intensity * 42
                        return (
                          <div
                            key={w.market_id || i}
                            onMouseEnter={() => setHoveredWeightIndex(i)}
                            onMouseLeave={() => setHoveredWeightIndex(null)}
                            className="relative p-3 text-left cursor-default transition-all duration-300 ease-out origin-center hover:scale-[1.03] hover:z-10"
                            style={{
                              gridColumn: isHovered ? '1 / -1' : undefined,
                            }}
                          >
                            <div
                              className="absolute inset-0 flex items-center justify-center pointer-events-none"
                              aria-hidden
                            >
                              <div
                                className="rounded-full aspect-square transition-all duration-300 ease-out"
                                style={{
                                  width: `${sizePct}%`,
                                  background: `radial-gradient(circle at 50% 50%, ${fill} 0%, ${fill} 55%, transparent 100%)`,
                                }}
                              />
                            </div>
                            <div className="relative z-10">
                              <p className="text-base font-medium text-black/90 leading-snug">
                                {isHovered ? w.title : firstThree(w.title)}
                                {!isHovered && (w.title || '').trim().split(/\s+/).length > 3 && '…'}
                              </p>
                              <p className="text-sm font-mono text-black/60 mt-0.5">
                                {pcts[i].toFixed(1)}%
                              </p>
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  </>
                )
              })()}
              {(!basketData?.weights?.length || basketLoading || basketError) && (
                <div className="flex-1 min-h-[200px] flex items-center justify-center text-black/40 text-base">
                  Weights appear when basket is loaded
                </div>
              )}
            </div>
          </div>
        </section>
        </div>
      </div>
    </div>
  )
}

function HomePage() {
  const [searchValue, setSearchValue] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [newsArticles, setNewsArticles] = useState([])
  const [newsLoading, setNewsLoading] = useState(true)
  const navigate = useNavigate()

  const NYT_CACHE_KEY = 'nyt_top_stories'
  const NYT_CACHE_TTL_MS = 15 * 60 * 1000 // 15 min
  const NYT_SECTION = 'home'

  useEffect(() => {
    let cancelled = false
    const cacheKey = `${NYT_CACHE_KEY}_${NYT_SECTION}`
    try {
      const raw = sessionStorage.getItem(cacheKey)
      if (raw) {
        const { data, ts } = JSON.parse(raw)
        if (Date.now() - ts < NYT_CACHE_TTL_MS && Array.isArray(data)) {
          setNewsArticles(data)
          setNewsLoading(false)
          return
        }
      }
    } catch (_) {}
    setNewsLoading(true)
    fetch(`/api/nytimes/top-stories?section=${encodeURIComponent(NYT_SECTION)}`)
      .then((res) => res.json())
      .then((data) => {
        if (!cancelled && Array.isArray(data)) {
          setNewsArticles(data)
          try {
            sessionStorage.setItem(cacheKey, JSON.stringify({ data, ts: Date.now() }))
          } catch (_) {}
        }
      })
      .catch(() => { if (!cancelled) setNewsArticles([]) })
      .finally(() => { if (!cancelled) setNewsLoading(false) })
    return () => { cancelled = true }
  }, [])

  function isPolymarketUrl(input) {
    const s = input.trim().toLowerCase()
    return (s.startsWith('http://') || s.startsWith('https://')) && s.includes('polymarket.com')
  }

  async function handleSearchSubmit(e) {
    e.preventDefault()
    const input = searchValue.trim()
    if (!input) return
    setError(null)
    setLoading(true)

    // For free-text prompts, navigate immediately — the results page runs the pipeline
    if (!isPolymarketUrl(input)) {
      setLoading(false)
      navigate('/search', { state: { prompt: input } })
      return
    }

    try {
      const res = await fetch(`/api/polymarket?url=${encodeURIComponent(input)}`)
      const data = await res.json()
      if (!res.ok) {
        setError(data?.detail ?? `Error ${res.status}`)
        setLoading(false)
        return
      }
      const slug = data.slug ?? (data.data?.[0]?.slug ?? data.data?.slug)
      setLoading(false)
      if (slug) {
        navigate(`/event/${slug}`, { state: { apiResponse: data } })
      } else {
        setError('Could not open event page')
      }
    } catch (err) {
      setError(err.message ?? 'Request failed')
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-blue-50 text-black flex flex-col overflow-x-hidden">
      <header className="sticky top-0 z-50 bg-blue-700">
        <nav className="mx-auto flex h-20 max-w-7xl items-center justify-between gap-6 px-2 md:px-3">
          <a href="/" className="flex items-center gap-2 shrink-0">
            <span className="flex h-8 w-8 items-center justify-center bg-white/20 font-bold text-white text-sm">PA</span>
            <span className="hidden font-semibold tracking-tight text-white sm:inline">Polymarket Arb</span>
          </a>
          <ul className="hidden flex-1 justify-end gap-8 md:flex">
            <li><a href="/" className="text-sm text-white hover:text-white/80">Home</a></li>
            <li><a href="/markets" className="text-sm text-white hover:text-white/80">Markets</a></li>
            <li><a href="/strategies" className="text-sm text-white hover:text-white/80">Strategies</a></li>
            <li><a href="/arb" className="text-sm text-white hover:text-white/80">Arbitrage</a></li>
          </ul>
        </nav>
      </header>

      <CryptoMarquee />

      <main className="relative flex flex-col flex-1 min-w-0">
        <section className="hero-gradient-drift flex min-h-[70vh] flex-col justify-center px-2 py-12 md:px-3 overflow-hidden">
          {/* Light translucent vector decoration */}
          <div className="absolute inset-0 z-0 pointer-events-none" aria-hidden>
            <svg className="absolute w-full h-full" viewBox="0 0 1200 600" preserveAspectRatio="xMidYMid slice" fill="none">
              <defs>
                <linearGradient id="hero-vec-grad" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stopColor="white" stopOpacity="0.08" />
                  <stop offset="100%" stopColor="white" stopOpacity="0.02" />
                </linearGradient>
              </defs>
              <path d="M0 200 Q300 100 600 200 T1200 200" stroke="url(#hero-vec-grad)" strokeWidth="1.5" fill="none" />
              <path d="M0 350 Q400 250 800 350 T1200 350" stroke="white" strokeOpacity="0.06" strokeWidth="1" fill="none" />
              <path d="M-50 450 Q200 380 500 450 T1200 450" stroke="white" strokeOpacity="0.05" strokeWidth="1" fill="none" />
              <ellipse cx="180" cy="120" rx="140" ry="80" fill="white" fillOpacity="0.04" />
              <ellipse cx="1000" cy="480" rx="200" ry="120" fill="white" fillOpacity="0.03" />
              <circle cx="950" cy="100" r="80" fill="white" fillOpacity="0.035" />
              <path d="M200 0 L200 600 M400 0 L400 600 M600 0 L600 600 M800 0 L800 600 M1000 0 L1000 600" stroke="white" strokeOpacity="0.04" strokeWidth="0.5" />
            </svg>
            <svg className="absolute top-0 right-0 w-[70%] h-full opacity-40" viewBox="0 0 400 600" preserveAspectRatio="xMaxYMid meet" fill="none">
              <path d="M400 0 L400 600 L0 400 Q200 200 400 0" fill="white" fillOpacity="0.06" />
              <path d="M350 0 L350 600 L50 450 Q150 250 350 0" fill="white" fillOpacity="0.03" />
            </svg>
            <svg className="absolute bottom-0 left-0 w-[50%] h-[60%] opacity-50" viewBox="0 0 300 400" preserveAspectRatio="xMinYMax meet" fill="none">
              <path d="M0 400 Q80 200 0 0 L0 400" fill="white" fillOpacity="0.05" />
              <circle cx="80" cy="320" r="120" fill="white" fillOpacity="0.03" />
            </svg>
          </div>
          <div className="relative z-10 mx-auto w-full max-w-7xl">
            <h1 className="text-4xl font-bold tracking-tight text-white md:text-5xl">Find markets</h1>
            <p className="mt-3 text-lg text-white/90">Build your own personalised prediction ETF</p>
            <form className="mt-8 max-w-2xl" onSubmit={handleSearchSubmit}>
              <div className="group relative flex w-full items-center border-0 pl-4 pr-4 md:pl-4">
                <div
                  className="pointer-events-none absolute inset-0 z-0"
                  style={{
                    background: 'linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.12) 10%, rgba(255,255,255,0.25) 22%, rgba(255,255,255,0.25) 78%, rgba(255,255,255,0.12) 90%, transparent 100%)',
                  }}
                />
                <div className="pointer-events-none absolute inset-0 z-0 bg-white/50 opacity-0 transition-opacity duration-300 group-focus-within:opacity-100" />
                <span className="relative z-10 flex shrink-0 text-white/90" aria-hidden>
                  <svg className="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                  </svg>
                </span>
                <input
                  type="search"
                  placeholder=""
                  aria-label="Search"
                  className="search-input relative z-10 w-full border-0 bg-transparent py-4 pl-3 pr-4 text-white placeholder-transparent outline-none"
                  value={searchValue}
                  onChange={(e) => setSearchValue(e.target.value)}
                  disabled={loading}
                />
              </div>
              {error && <p className="mt-2 text-sm text-red-200">{error}</p>}
            </form>
          </div>
        </section>

        <div className="mx-auto w-full max-w-7xl flex-1 px-2 py-8 md:px-3 min-w-0">
          <Section title="News">
            {newsLoading ? (
              <div className="flex items-center justify-center py-12 text-black/50">Loading news…</div>
            ) : newsArticles.length === 0 ? (
              <div className="py-12 text-center text-black/50">No articles. Set NYTIMES_API_KEY on the server to enable.</div>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {newsArticles.slice(0, 4).map((article) => {
                  const dateStr = article.published_date
                    ? new Date(article.published_date).toLocaleDateString(undefined, { dateStyle: 'medium' })
                    : ''
                  const source = 'The New York Times'
                  return (
                    <a
                      key={article.id}
                      href={article.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="group relative flex overflow-hidden border border-gray-200 bg-white shadow-sm text-left min-h-[140px] cursor-pointer"
                    >
                      <div className="w-[30%] shrink-0 overflow-hidden bg-gray-100">
                        {article.image_url ? (
                          <img src={article.image_url} alt="" className="h-full w-full object-cover min-h-full group-hover:scale-[1.03] transition-transform duration-300" />
                        ) : (
                          <div className="h-full min-h-[140px] flex items-center justify-center">
                            <span className="text-gray-400 text-xs">No image</span>
                          </div>
                        )}
                      </div>
                      <div className="relative flex-1 flex min-w-0 overflow-hidden">
                        <span className="absolute left-0 top-0 bottom-0 w-0 bg-blue-700 group-hover:w-1/2 transition-[width] duration-300 ease-out pointer-events-none" aria-hidden />
                        <span className="absolute right-0 top-0 bottom-0 w-0 bg-blue-700 group-hover:w-1/2 transition-[width] duration-300 ease-out pointer-events-none" aria-hidden />
                        <div className="relative flex-1 flex flex-col justify-center p-4 min-w-0 z-10">
                          <h3 className="font-semibold text-lg text-black group-hover:text-white transition-colors duration-300 line-clamp-2">{article.title}</h3>
                          <p className="mt-1 text-sm text-black/60 group-hover:text-white/90 transition-colors duration-300">{dateStr}</p>
                        </div>
                        <div className="flex shrink-0 items-center justify-center py-4 pr-3 w-10 z-10">
                          <span
                            className="text-xs font-medium uppercase tracking-wider text-blue-700 group-hover:text-white/90 transition-colors duration-300 whitespace-nowrap"
                            style={{ writingMode: 'vertical-rl', textOrientation: 'mixed', transform: 'rotate(180deg)' }}
                          >
                            {source}
                          </span>
                        </div>
                      </div>
                    </a>
                  )
                })}
              </div>
            )}
          </Section>
        </div>
      </main>
    </div>
  )
}

const LABEL_COLORS = {
  Person: '#2563eb',
  Company: '#16a34a',
  Event: '#d97706',
  Market: '#dc2626',
}

function GraphAnalysisPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const prompt = location.state?.prompt ?? null
  const [navSearchValue, setNavSearchValue] = useState('')
  const [layers, setLayers] = useState([])
  const [startNodes, setStartNodes] = useState([])
  const [keywords, setKeywords] = useState([])
  const [currentLayer, setCurrentLayer] = useState(-1)
  const [visibleThroughLayer, setVisibleThroughLayer] = useState(null) // null = show all; number = show layers 0..visibleThroughLayer
  const [phase, setPhase] = useState('idle')
  const [error, setError] = useState(null)
  const graphRef = useRef(null)
  const containerRef = useRef(null)
  const [dimensions, setDimensions] = useState({ width: 800, height: 500 })
  const revealStartTimeRef = useRef(Date.now())

  function handleNavSearchSubmit(e) {
    e.preventDefault()
    const input = navSearchValue.trim()
    if (!input) return
    navigate('/search', { state: { prompt: input } })
  }

  useEffect(() => {
    function measure() {
      setDimensions({ width: window.innerWidth, height: window.innerHeight })
    }
    measure()
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [])

  useEffect(() => {
    if (!prompt) return
    setPhase('loading')
    setError(null)
    setLayers([])
    setStartNodes([])
    setKeywords([])
    setCurrentLayer(-1)
    setVisibleThroughLayer(null)
    let cancelled = false
    async function fetchBFS() {
      try {
        const res = await fetch(`/api/graph/bfs-layers?q=${encodeURIComponent(prompt)}&max_depth=4`)
        if (cancelled) return
        const data = await res.json()
        if (!res.ok) {
          setError(data?.detail ?? 'Graph query failed')
          setPhase('error')
          return
        }
        if (!data.layers?.length) {
          setError('No graph nodes found for this query.')
          setPhase('error')
          return
        }
        setLayers(data.layers)
        setStartNodes(data.start_nodes ?? [])
        setKeywords(data.keywords ?? [])
        setPhase('animating')
        setCurrentLayer(0)
      } catch (e) {
        if (!cancelled) {
          setError(e.message ?? 'Request failed')
          setPhase('error')
        }
      }
    }
    fetchBFS()
    return () => { cancelled = true }
  }, [prompt])

  useEffect(() => {
    if (phase !== 'animating' || currentLayer < 0) return
    revealStartTimeRef.current = Date.now()
    if (currentLayer >= layers.length - 1) {
      setPhase('complete')
      return
    }
    const timer = setTimeout(() => setCurrentLayer((c) => c + 1), 1000)
    return () => clearTimeout(timer)
  }, [phase, currentLayer, layers.length])

  useEffect(() => {
    if (graphRef.current && currentLayer === 0) {
      setTimeout(() => graphRef.current?.zoomToFit?.(400, 60), 200)
    }
  }, [currentLayer])

  const graphData = useMemo(() => {
    if (currentLayer < 0 || !layers.length) return { nodes: [], links: [] }
    const seen = new Set()
    const nodes = []
    const links = []
    const cap = visibleThroughLayer !== null ? Math.min(visibleThroughLayer, layers.length - 1) : layers.length - 1
    const maxLayer = Math.min(currentLayer, cap)
    for (let i = 0; i <= maxLayer; i++) {
      const layer = layers[i]
      for (const n of layer.nodes ?? []) {
        const id = n.id ?? n.name
        if (id != null && !seen.has(id)) {
          seen.add(id)
          nodes.push({ ...n, layer: i })
        }
      }
      for (const l of layer.links ?? []) {
        links.push({ ...l })
      }
    }
    return { nodes, links }
  }, [currentLayer, layers, visibleThroughLayer])

  const nodeCanvasObject = useCallback((node, ctx, globalScale) => {
    const layer = node.layer ?? 0
    const isCurrentWave = layer === currentLayer && phase === 'animating'
    const waveMs = 450
    const elapsed = Date.now() - revealStartTimeRef.current
    const opacity = isCurrentWave ? Math.min(1, elapsed / waveMs) : 1
    const label = node.name || ''
    const fontSize = Math.max(11 / globalScale, 2)
    const primaryLabel = (node.labels ?? []).find((l) => l in LABEL_COLORS)
    const color = LABEL_COLORS[primaryLabel] ?? '#6b7280'
    const r = 4 + (layer === 0 ? 3 : 0)
    ctx.save()
    ctx.globalAlpha = opacity
    ctx.beginPath()
    ctx.arc(node.x, node.y, r, 0, 2 * Math.PI, false)
    ctx.fillStyle = color
    ctx.fill()
    if (globalScale > 0.6) {
      ctx.font = `${fontSize}px sans-serif`
      ctx.textAlign = 'center'
      ctx.textBaseline = 'top'
      ctx.fillStyle = '#1f2937'
      const maxLen = 24
      const display = label.length > maxLen ? label.slice(0, maxLen - 1) + '…' : label
      ctx.fillText(display, node.x, node.y + r + 2)
    }
    ctx.restore()
  }, [currentLayer, phase])

  const stepLabels = layers.map((_, i) =>
    i === 0 ? 'Start nodes' : `Layer ${i}`
  )

  const graphBg = 'oklch(97% 0.014 254.604)'

  return (
    <div className="fixed inset-0 flex flex-col text-black" style={{ background: graphBg }}>
      {/* Full-page force graph */}
      <div
        ref={containerRef}
        className="absolute inset-0 overflow-hidden"
        style={{ background: graphBg }}
      >
        {graphData.nodes.length > 0 && (
          <ForceGraph2D
            ref={graphRef}
            graphData={graphData}
            width={dimensions.width}
            height={dimensions.height}
            backgroundColor={graphBg}
            nodeCanvasObject={nodeCanvasObject}
            nodePointerAreaPaint={(node, color, ctx) => {
              ctx.beginPath()
              ctx.arc(node.x, node.y, 8, 0, 2 * Math.PI)
              ctx.fillStyle = color
              ctx.fill()
            }}
            linkColor={() => 'rgba(100,116,139,0.35)'}
            linkWidth={1}
            cooldownTicks={80}
            d3VelocityDecay={0.3}
            enableZoomInteraction
            enablePanInteraction
          />
        )}
      </div>

      {/* Overlay card: nav, title, steps, legend */}
      <div className="absolute top-4 left-4 z-10 w-full max-w-sm">
        <div
          className="border border-black/8 bg-blue-50/75 shadow-xl backdrop-blur-md p-4 space-y-3"
          style={{ boxShadow: '0 8px 32px rgba(0,0,0,0.08), 0 0 0 1px rgba(255,255,255,0.5) inset' }}
        >
          <div className="flex items-center justify-between gap-2">
            <a href="/" className="flex items-center gap-2 shrink-0 text-black/70 hover:text-black">
              <span className="flex h-7 w-7 items-center justify-center rounded bg-black/10 font-bold text-xs">PA</span>
              <span className="text-sm font-medium">Polymarket Arb</span>
            </a>
            <form className="flex-1 min-w-0" onSubmit={handleNavSearchSubmit}>
              <div className="flex items-center rounded-lg bg-black/5 border border-black/8 px-2.5 py-1.5 focus-within:border-blue-400 focus-within:ring-1 focus-within:ring-blue-400">
                <span className="text-black/50 mr-1.5" aria-hidden>
                  <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                  </svg>
                </span>
                <input
                  type="search"
                  placeholder="New search…"
                  aria-label="New search"
                  className="w-full bg-transparent text-sm text-black placeholder-black/40 outline-none"
                  value={navSearchValue}
                  onChange={(e) => setNavSearchValue(e.target.value)}
                />
              </div>
            </form>
          </div>
          {prompt && (
            <h1 className="text-base font-medium text-black/85 truncate" title={prompt}>
              Graph: &quot;{prompt}&quot;
            </h1>
          )}

          {/* Keywords used to traverse the graph */}
          {keywords.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[11px] font-medium text-black/50 uppercase tracking-wide shrink-0">Traverse keywords</span>
              <span className="text-[11px] text-black/70">
                {keywords.map((kw, i) => (
                  <span key={kw}>
                    <span className="rounded bg-black/8 px-1.5 py-0.5 font-mono">{kw}</span>
                    {i < keywords.length - 1 && <span className="mx-0.5 text-black/40">·</span>}
                  </span>
                ))}
              </span>
            </div>
          )}

          {/* Thinking steps */}
          <div className="space-y-1.5">
            {phase === 'loading' && (
              <div className="flex items-center gap-2">
                <Spinner />
                <span className="text-xs text-black/60">Resolving query and traversing graph…</span>
              </div>
            )}
            {(phase === 'animating' || phase === 'complete') && stepLabels.map((label, i) => {
              const done = i <= currentLayer
              const active = i === currentLayer && phase === 'animating'
              const removed = visibleThroughLayer !== null && i > visibleThroughLayer
              const layerData = layers[i]
              const nodeCount = layerData?.nodes?.length ?? 0
              const linkCount = layerData?.links?.length ?? 0
              const handleLayerClick = () => {
                if (removed) {
                  setVisibleThroughLayer(i)
                } else {
                  setVisibleThroughLayer(i - 1)
                }
              }
              return (
                <button
                  key={i}
                  type="button"
                  onClick={handleLayerClick}
                  className="flex items-center gap-2 flex-wrap w-full text-left rounded px-1 -mx-1 py-0.5 hover:bg-black/5 transition-colors cursor-pointer"
                  title={removed ? `Show through ${label}` : `Remove ${label} and later layers`}
                >
                  <div
                    className="w-1.5 h-1.5 rounded-full shrink-0 transition-colors duration-300"
                    style={{ backgroundColor: removed ? '#d1d5db' : done ? '#16a34a' : active ? '#2563eb' : '#d1d5db' }}
                  />
                  <span className={`text-xs font-medium ${removed ? 'text-black/40 line-through' : 'text-black/70'}`}>
                    {label}
                  </span>
                  {active && <Spinner />}
                  {done && !removed && (
                    <span className="text-[11px] text-black/40 font-mono">{nodeCount}n · {linkCount}e</span>
                  )}
                </button>
              )
            })}
            {phase === 'complete' && (
              <div className="flex items-center gap-2">
                <div className="w-1.5 h-1.5 rounded-full shrink-0 bg-green-600" />
                <span className="text-xs font-medium text-green-700">Complete</span>
              </div>
            )}
            {phase === 'error' && error && (
              <p className="text-xs text-red-600">{error}</p>
            )}
          </div>

          {/* Legend */}
          {(phase === 'animating' || phase === 'complete') && (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 pt-1 border-t border-black/8">
              {Object.entries(LABEL_COLORS).map(([label, color]) => (
                <div key={label} className="flex items-center gap-1">
                  <div className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: color }} />
                  <span className="text-[11px] text-black/50">{label}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/search" element={<SemanticResultsPage />} />
      <Route path="/search/graph" element={<GraphAnalysisPage />} />
      <Route path="/event/:slug" element={<EventPage />} />
    </Routes>
  )
}

export default App
