import { useEffect, useState, useMemo, useRef } from 'react'
import { Routes, Route, useNavigate, useLocation, useParams } from 'react-router-dom'
import { ResponsiveContainer, AreaChart, Area, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts'

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

function EventPage() {
  const { slug } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const [apiResponse, setApiResponse] = useState(location.state?.apiResponse ?? null)
  const [loading, setLoading] = useState(!location.state?.apiResponse)
  const [error, setError] = useState(null)
  const [priceHistory, setPriceHistory] = useState(null)
  const [chartInterval, setChartInterval] = useState('1d')

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

  return (
    <div className="min-h-screen bg-blue-50 text-black flex flex-col">
      <BlueSwipe />
      {/* Header */}
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
            <button
              type="button"
              onClick={() => navigate('/')}
              className="bg-white/20 px-4 py-1.5 text-sm font-medium text-white hover:bg-white/30"
            >
              New search
            </button>
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
              <div className="inline-flex border border-gray-300 bg-white shadow-sm" role="tablist" aria-label="Chart time range">
                {[
                  { value: '1d', label: '1D' },
                  { value: '1w', label: '1W' },
                  { value: 'max', label: '1M' },
                ].map(({ value, label }) => (
                  <button
                    key={value}
                    type="button"
                    role="tab"
                    aria-selected={chartInterval === value}
                    onClick={() => setChartInterval(value)}
                    className={`px-4 py-2 text-sm font-medium border-r border-gray-300 last:border-r-0 transition-colors ${
                      chartInterval === value
                        ? 'bg-gray-900 text-white'
                        : 'bg-white text-black hover:bg-gray-100'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
            <div className="flex-1 min-h-0">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={chartData} margin={{ top: 12, right: 16, bottom: 8, left: 8 }}>
                  <defs>
                    <linearGradient id="chartGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={chartColor} stopOpacity={0.35} />
                      <stop offset="100%" stopColor={chartColor} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" vertical={false} />
                  <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#999' }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 10, fill: '#999' }} axisLine={false} tickLine={false} tickFormatter={(v) => `${v}¢`} domain={['dataMin - 0.5', 'dataMax + 0.5']} />
                  <Tooltip
                    contentStyle={{ fontSize: 12, border: '1px solid #e5e7eb', boxShadow: 'none' }}
                    formatter={(v) => [`${v.toFixed(1)}¢`, 'Price']}
                    labelStyle={{ fontSize: 11, color: '#666' }}
                  />
                  <Area type="monotone" dataKey="price" stroke={chartColor} strokeWidth={1.5} fill="url(#chartGrad)" dot={false} activeDot={{ r: 3, fill: chartColor }} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* News */}
          <div className="pt-6">
            <h3 className="px-6 pb-4 text-2xl font-semibold text-black">News</h3>
            <ul>
              <li className="flex items-center gap-4 border-t border-black/10 px-6 py-4">
                <img src="https://picsum.photos/96/96?random=1" alt="" className="h-20 w-20 shrink-0 object-cover" />
                <div className="min-w-0 flex-1">
                  <span className="text-base text-black">Musk tweets "buying Ryanair might be a good idea" amid aviation sector rally</span>
                </div>
                <span className="text-sm text-black/50 shrink-0">Reuters</span>
              </li>
              <li className="flex items-center gap-4 border-t border-black/10 px-6 py-4">
                <img src="https://picsum.photos/96/96?random=2" alt="" className="h-20 w-20 shrink-0 object-cover" />
                <div className="min-w-0 flex-1">
                  <span className="text-base text-black">Ryanair shares jump 8% on speculation of potential Musk acquisition offer</span>
                </div>
                <span className="text-sm text-black/50 shrink-0">Bloomberg</span>
              </li>
              <li className="flex items-center gap-4 border-t border-black/10 px-6 py-4">
                <img src="https://picsum.photos/96/96?random=3" alt="" className="h-20 w-20 shrink-0 object-cover" />
                <div className="min-w-0 flex-1">
                  <span className="text-base text-black">EU regulators signal any airline acquisition would face antitrust review</span>
                </div>
                <span className="text-sm text-black/50 shrink-0">FT</span>
              </li>
            </ul>
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
        if (!best || (best.score ?? 0) <= 0.7) {
          setBasketLoading(false)
          return
        }
        // Use only best_market.id (same source as inputs) — match word-search best to an event’s best_market
        // best.id is same field as best_market.id (backend resolves word-search ids via Gamma)
        const targetMarketId = best.id
        const excludeIds = new Set([targetMarketId, ...wordSearchMarkets.map((m) => m.id)])
        const inputIds = events
          .map((e) => e.best_market?.id)
          .filter(Boolean)
          .filter((id) => !excludeIds.has(id))
          .slice(0, 10)
        if (inputIds.length === 0) {
          setBasketLoading(false)
          return
        }
        console.log('Target market ID sent to backend:', targetMarketId)
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
      <header className="sticky top-0 z-50 bg-blue-700">
        <nav className="flex h-20 items-center justify-between px-4 md:px-6">
          <a href="/" className="flex items-center gap-2 shrink-0">
            <span className="flex h-8 w-8 items-center justify-center bg-white/20 font-bold text-white text-sm">PA</span>
            <span className="hidden font-semibold tracking-tight text-white sm:inline">Polymarket Arb</span>
          </a>
          <button type="button" onClick={() => navigate('/')} className="text-base text-white/80 hover:text-white underline underline-offset-2">
            New search
          </button>
        </nav>
      </header>

      <div className="mx-auto w-full max-w-4xl px-6 md:px-10 pt-14 pb-24">
        <h1 className="text-3xl font-medium tracking-tight text-black/80 mb-2">"{prompt}"</h1>
        <div className="h-px bg-black/10 mb-12" />

        {error && (
          <p className="step-appear text-base text-red-600 mb-8">{error}</p>
        )}

        {/* Pipeline: collapsible when complete */}
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

        {/* Graph section: target vs synthetic time series */}
        <div className="h-px bg-black/10 mt-12 mb-4" />
        <section className="mb-8">
          <h2 className="text-sm font-medium text-black/40 uppercase tracking-wider mb-4">
            Target vs synthetic
          </h2>
          <div className="min-h-[280px] flex flex-col items-center justify-center">
            {basketLoading && (
              <p className="text-black/50 flex items-center gap-2">
                <Spinner />
                Loading basket and time series…
              </p>
            )}
            {!basketLoading && basketError && (
              <p className="text-red-600">{basketError}</p>
            )}
            {!basketLoading && !basketError && !basketData && (
              <p className="text-black/50 text-center max-w-md">
                If a search returns a strong text match (&gt;70%), the target market and synthetic basket time series will appear here.
              </p>
            )}
            {!basketLoading && !basketError && basketData && (() => {
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
                <div className="w-full">
                  <p className="text-sm text-black/60 mb-2 truncate" title={basketData.target_question}>
                    {basketData.target_question}
                  </p>
                  {basketData.r_squared != null && (
                    <p className="text-xs text-black/40 mb-2">R² = {Number(basketData.r_squared).toFixed(4)}</p>
                  )}
                  <div className="w-full h-[260px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={chartData} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                        <XAxis dataKey="date" tick={{ fontSize: 11 }} stroke="#9ca3af" />
                        <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} stroke="#9ca3af" tickFormatter={(v) => `${v}%`} />
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
        </section>
      </div>
    </div>
  )
}

function HomePage() {
  const [searchValue, setSearchValue] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const navigate = useNavigate()

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

      <div className="bg-blue-700 text-white" style={{ backgroundColor: '#1d4ed8' }}>
        <div className="flex items-center gap-4 overflow-hidden py-3">
          <div className="flex shrink-0 items-center gap-2 px-4">
            <span className="flex h-6 w-6 items-center justify-center bg-white/20 text-white">
              <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
              </svg>
            </span>
            <span className="text-sm font-medium text-white">Trending</span>
          </div>
          <div className="ticker-wrap flex-1 overflow-hidden">
            <div className="ticker flex gap-8 whitespace-nowrap">
              {['Election market: Trump vs Harris odds shift after debate.', 'Fed rate market: June cut probability at 72%.', 'Related market: Crypto ETF approval moves correlation markets.'].map((headline, i) => (
                <span key={i} className="text-sm text-white">{headline}</span>
              ))}
              {['Election market: Trump vs Harris odds shift after debate.', 'Fed rate market: June cut probability at 72%.', 'Related market: Crypto ETF approval moves correlation markets.'].map((headline, i) => (
                <span key={`dup-${i}`} className="text-sm text-white">{headline}</span>
              ))}
            </div>
          </div>
          <button type="button" className="shrink-0 bg-white/20 px-4 py-1.5 text-sm font-medium text-white hover:bg-white/30">All news</button>
        </div>
      </div>

      <main className="relative flex flex-col flex-1 min-w-0">
        <section className="hero-gradient-drift flex min-h-[70vh] flex-col justify-center px-2 py-12 md:px-3">
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

        <div className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-8 px-2 py-8 md:px-3 lg:flex-row min-w-0">
          <div className="flex min-h-[200px] min-w-0 flex-[0.35] items-center justify-center bg-white lg:min-h-0">
            <div className="flex flex-col items-center justify-center gap-2">
              <div className="h-12 w-12 bg-blue-700" />
              <span className="text-xs text-black">Insight</span>
            </div>
          </div>
          <div className="flex min-w-0 flex-[0.65] flex-col">
            <p className="mb-4 text-sm font-medium text-black">Trending now:</p>
            <div className="grid grid-cols-2 lg:grid-cols-3 [&>*]:border-t [&>*]:border-l [&>*]:border-blue-700 [&>*:nth-child(2n)]:border-r [&>*:nth-child(n+5)]:border-b lg:[&>*:nth-child(2n)]:border-r-0 lg:[&>*:nth-child(3n)]:border-r lg:[&>*:nth-child(n+4)]:border-b">
              {[
                { label: 'Track Fed rates', meta: 'Macro' },
                { label: 'Track election odds', meta: 'Politics' },
                { label: 'Track crypto markets', meta: 'Crypto' },
                { label: 'Related markets', meta: 'See dashboard' },
                { label: 'Arbitrage opportunities', meta: 'See dashboard' },
                { label: 'Causality signals', meta: 'See dashboard' },
              ].map((item, i) => (
                <button key={i} type="button" className="group relative flex items-center gap-4 overflow-hidden bg-white p-4 text-left">
                  <span className="absolute inset-y-0 left-0 w-0 bg-blue-700 transition-[width] duration-500 ease-[cubic-bezier(0.4,0,0.2,1)] group-hover:w-full" aria-hidden />
                  <span className="relative z-10 flex h-10 w-10 shrink-0 items-center justify-center bg-blue-700 text-white group-hover:bg-white group-hover:text-blue-700">
                    <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
                    </svg>
                  </span>
                  <div className="relative z-10 min-w-0">
                    <span className="block font-medium text-black transition-colors group-hover:text-white">{item.label}</span>
                    <span className="block text-xs text-black transition-colors group-hover:text-white/90">{item.meta}</span>
                  </div>
                </button>
              ))}
            </div>
            <div className="mt-6 grid grid-cols-3">
              {[
                { sym: 'TRUMP', price: '58¢', name: 'Trump wins 2024', chg: '+2.1%', up: true },
                { sym: 'FED', price: '72¢', name: 'Rate cut Jun', chg: '-0.8%', up: false },
                { sym: 'BTC', price: '91¢', name: 'BTC > 100k', chg: '+1.2%', up: true },
              ].map((m) => (
                <div key={m.sym} className={`border-l-4 p-4 ${m.up ? 'border-l-green-600' : 'border-l-red-600'}`}>
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-sm font-medium text-black">{m.sym}</span>
                    <span className={`text-sm font-medium ${m.up ? 'text-green-700' : 'text-red-700'}`}>{m.chg}</span>
                  </div>
                  <p className={`mt-1 text-lg font-semibold ${m.up ? 'text-green-700' : 'text-red-700'}`}>{m.price}</p>
                  <p className="text-xs text-black">{m.name}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}

function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/search" element={<SemanticResultsPage />} />
      <Route path="/event/:slug" element={<EventPage />} />
    </Routes>
  )
}

export default App
