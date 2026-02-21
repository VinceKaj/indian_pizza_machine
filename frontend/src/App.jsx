function App() {
  return (
    <div className="min-h-screen bg-[#0f0f12] text-slate-100 flex flex-col">
      {/* Top nav */}
      <header className="sticky top-0 z-50 bg-[#0f0f12]/95 backdrop-blur">
        <nav className="mx-auto flex h-14 max-w-7xl items-center justify-between gap-6 px-4">
          <a href="/" className="flex items-center gap-2 shrink-0">
            <span className="flex h-8 w-8 items-center justify-center bg-emerald-500 font-bold text-[#0f0f12] text-sm">
              PA
            </span>
            <span className="hidden font-semibold tracking-tight sm:inline">
              Polymarket Arb
            </span>
          </a>

          <ul className="hidden flex-1 justify-center gap-8 md:flex">
            <li><a href="/" className="text-sm text-slate-300 hover:text-white">Home</a></li>
            <li><a href="/markets" className="text-sm text-slate-300 hover:text-white">Markets</a></li>
            <li><a href="/strategies" className="text-sm text-slate-300 hover:text-white">Strategies</a></li>
            <li><a href="/arb" className="text-sm text-slate-300 hover:text-white">Arbitrage</a></li>
            <li><a href="/pricing" className="text-sm text-slate-300 hover:text-white">Pricing</a></li>
          </ul>

          <div className="flex flex-1 items-center justify-end gap-3 md:flex-initial">
            <label className="hidden w-44 bg-slate-800/50 px-3 py-2 md:flex md:items-center md:gap-2 focus-within:outline focus-within:outline-2 focus-within:outline-emerald-500 outline-none">
              <svg className="h-4 w-4 shrink-0 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
              <input type="search" placeholder="Search markets..." className="w-full min-w-0 bg-transparent text-sm text-white placeholder-slate-500 outline-none" />
            </label>
            <button type="button" className="px-3 py-2 text-sm text-slate-300 hover:bg-slate-800 hover:text-white">
              Sign In
            </button>
            <button type="button" className="bg-emerald-500 px-4 py-2 text-sm font-medium text-[#0f0f12] hover:bg-emerald-400">
              Join
            </button>
          </div>
        </nav>
      </header>

      {/* Hero + main */}
      <main className="relative flex-1">
        <div className="mx-auto max-w-7xl px-4 py-12 md:py-16">
          <div className="grid gap-10 lg:grid-cols-[1fr,minmax(280px,400px)] lg:gap-8">
            <div>
              <h1 className="text-4xl font-bold tracking-tight text-white md:text-5xl">
                Trade like an insider.
              </h1>
              <p className="mt-3 text-lg text-slate-400">
                Find related markets and arbitrage from causality.
              </p>

              {/* Hero search bar */}
              <div className="mt-8 flex bg-slate-800/50 focus-within:outline focus-within:outline-2 focus-within:outline-emerald-500">
                <span className="flex items-center pl-4 text-slate-500">
                  <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                  </svg>
                </span>
                <input
                  type="search"
                  placeholder="Search markets, events, and more..."
                  className="w-full bg-transparent py-4 pr-4 pl-3 text-white placeholder-slate-500 outline-none"
                />
              </div>

              {/* Trending Now ribbon */}
              <div className="mt-14">
                <p className="mb-4 text-sm font-medium text-slate-400">
                  Trending now:
                </p>
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  {[
                    { label: 'Track Fed rates', meta: 'Macro' },
                    { label: 'Track election odds', meta: 'Politics' },
                    { label: 'Track crypto markets', meta: 'Crypto' },
                    { label: 'Related markets', meta: 'See dashboard' },
                    { label: 'Arbitrage opportunities', meta: 'See dashboard' },
                    { label: 'Causality signals', meta: 'See dashboard' },
                  ].map((item, i) => (
                    <button
                      key={i}
                      type="button"
                      className="flex items-center gap-4 bg-slate-800/40 p-4 text-left transition hover:bg-slate-800/70"
                    >
                      <span className="flex h-10 w-10 shrink-0 items-center justify-center bg-slate-700/80 text-emerald-400">
                        <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
                        </svg>
                      </span>
                      <div className="min-w-0">
                        <span className="block font-medium text-white">{item.label}</span>
                        <span className="block text-xs text-slate-500">{item.meta}</span>
                      </div>
                    </button>
                  ))}
                </div>
              </div>

              {/* Market ticker cards row */}
              <div className="mt-6 grid gap-4 sm:grid-cols-3">
                {[
                  { sym: 'TRUMP', price: '58¢', name: 'Trump wins 2024', chg: '+2.1%', up: true },
                  { sym: 'FED', price: '72¢', name: 'Rate cut Jun', chg: '-0.8%', up: false },
                  { sym: 'BTC', price: '91¢', name: 'BTC > 100k', chg: '+1.2%', up: true },
                ].map((m) => (
                  <div
                    key={m.sym}
                    className="bg-slate-800/40 p-4"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-sm font-medium text-slate-300">{m.sym}</span>
                      <span className={`text-sm font-medium ${m.up ? 'text-emerald-400' : 'text-red-400'}`}>{m.chg}</span>
                    </div>
                    <p className="mt-1 text-lg font-semibold text-white">{m.price}</p>
                    <p className="text-xs text-slate-500">{m.name}</p>
                  </div>
                ))}
              </div>
            </div>

            {/* Decorative panel (isometric-style placeholder) */}
            <div className="hidden items-center justify-center bg-linear-to-br from-slate-800/80 to-slate-900/80 lg:flex">
              <div className="flex h-48 w-48 flex-col items-center justify-center gap-2 bg-slate-800/50">
                <div className="h-12 w-12 bg-emerald-500/20" />
                <span className="text-xs text-slate-500">Insight</span>
              </div>
            </div>
          </div>
        </div>
      </main>

      {/* Bottom news ribbon */}
      <footer className="bg-slate-900/50">
        <div className="flex items-center gap-4 overflow-hidden py-3">
          <div className="flex shrink-0 items-center gap-2 px-4">
            <span className="flex h-6 w-6 items-center justify-center bg-emerald-500/20 text-emerald-400">
              <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
              </svg>
            </span>
            <span className="text-sm font-medium text-slate-300">Trending</span>
          </div>
          <div className="ticker-wrap flex-1 overflow-hidden">
            <div className="ticker flex gap-8 whitespace-nowrap">
              {[
                'Election market: Trump vs Harris odds shift after debate.',
                'Fed rate market: June cut probability at 72%.',
                'Related market: Crypto ETF approval moves correlation markets.',
              ].map((headline, i) => (
                <span key={i} className="text-sm text-slate-400">
                  {headline}
                </span>
              ))}
              {[
                'Election market: Trump vs Harris odds shift after debate.',
                'Fed rate market: June cut probability at 72%.',
                'Related market: Crypto ETF approval moves correlation markets.',
              ].map((headline, i) => (
                <span key={`dup-${i}`} className="text-sm text-slate-400">
                  {headline}
                </span>
              ))}
            </div>
          </div>
          <button type="button" className="shrink-0 bg-emerald-500 px-4 py-1.5 text-sm font-medium text-[#0f0f12] hover:bg-emerald-400">
            All news
          </button>
        </div>
      </footer>
    </div>
  )
}

export default App
