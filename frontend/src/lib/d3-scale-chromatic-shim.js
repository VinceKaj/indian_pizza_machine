/**
 * Minimal shim for d3-scale-chromatic when the package's src tree is incomplete.
 * Exports only what force-graph uses: schemePaired.
 */
function colors(specifier) {
  const n = (specifier.length / 6) | 0
  const out = new Array(n)
  let i = 0
  while (i < n) out[i] = '#' + specifier.slice(i * 6, ++i * 6)
  return out
}

export const schemePaired = colors('a6cee31f78b4b2df8a33a02cfb9a99e31a1cfdbf6fff7f00cab2d66a3d9affff99b15928')

// Re-export common categorical schemes so any other importer gets a valid module
export const schemeCategory10 = colors('1f77b4ff7f0e2ca02cd627289467bd8c564be377c27f7f7fbcbd2217becf')
export const schemeAccent = colors('7fc97fbeaed4fdc086ffff99386cb0f0027fbf5b17666666')
export const schemeDark2 = colors('1b9e77d95f027570b3e7298a66a61ee6ab02a6761d666666')
export const schemeSet1 = colors('e41a1c377eb84daf4a984ea3ff7f00ffff33a65628f781bf999999')
export const schemeSet2 = colors('66c2a5fc8d628da0cbe78ac3a6d854ffd92fe5c494b3b3b3')
export const schemeSet3 = colors('8dd3c7ffffb3bebadafb807280b1d3fdb462b3de69fccde5d9d9d9bc80bdccebc5ffed6f')
export const schemeTableau10 = colors('4e79a7f28e2ce1575976b7b259a14fedc949af7aa1ff9da79c755fbab0ab')
