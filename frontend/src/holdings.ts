/** Parse the app's simple ticker,shares CSV export/import format. */
export function parseHoldingsCsv(text: string): Record<string, number> {
  const lines = text.trim().split(/\r?\n/).filter(Boolean)
  const header = lines.shift()?.split(',').map(part => part.trim().toLowerCase()) ?? []
  const tickerIndex = header.indexOf('ticker')
  const sharesIndex = header.indexOf('shares')
  if (tickerIndex < 0 || sharesIndex < 0) throw new Error('CSV needs ticker and shares columns.')
  const holdings: Record<string, number> = {}
  for (const [index, line] of lines.entries()) {
    const cells = line.split(',').map(part => part.trim())
    const ticker = (cells[tickerIndex] ?? '').toUpperCase()
    const shares = Number(cells[sharesIndex])
    if (!/^[A-Z0-9.^-]{1,16}$/.test(ticker)) throw new Error(`Invalid ticker on CSV row ${index + 2}.`)
    if (!Number.isSafeInteger(shares) || shares < 0 || cells[sharesIndex] === '') {
      throw new Error(`Shares must be a nonnegative whole number on CSV row ${index + 2}.`)
    }
    if (ticker in holdings) throw new Error(`Duplicate ticker ${ticker} in CSV.`)
    holdings[ticker] = shares
  }
  return holdings
}

/** Replace a holdings snapshot, setting omitted current shares to zero. */
export function replaceHoldingShares<T extends { ticker: string; shares: number }>(
  rows: T[], holdings: Record<string, number>, newRow: (ticker: string, shares: number) => T,
): T[] {
  const existing = new Set(rows.map(row => row.ticker))
  return [
    ...rows.map(row => ({ ...row, shares: holdings[row.ticker] ?? 0 })),
    ...Object.entries(holdings).filter(([ticker]) => !existing.has(ticker))
      .map(([ticker, shares]) => newRow(ticker, shares)),
  ]
}
