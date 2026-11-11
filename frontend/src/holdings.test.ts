import { describe, expect, it } from 'vitest'
import { parseHoldingsCsv, replaceHoldingShares } from './holdings'

describe('paper holdings CSV', () => {
  it('reads ticker shares without code or JSON', () => {
    expect(parseHoldingsCsv('ticker,shares\nSPY,3\nSH,0\n')).toEqual({ SPY: 3, SH: 0 })
  })
  it('rejects fractions and repeated tickers', () => {
    expect(() => parseHoldingsCsv('ticker,shares\nSPY,1.5')).toThrow('whole number')
    expect(() => parseHoldingsCsv('ticker,shares\nSPY,1\nSPY,2')).toThrow('Duplicate')
  })
  it('replaces prior shares when a later CSV omits a ticker', () => {
    const rows = [{ ticker: 'SPY', shares: 4 }, { ticker: 'SH', shares: 9 }]
    const imported = replaceHoldingShares(rows, { SPY: 2, GLD: 3 }, (ticker, shares) => ({ ticker, shares }))
    expect(imported).toEqual([
      { ticker: 'SPY', shares: 2 }, { ticker: 'SH', shares: 0 }, { ticker: 'GLD', shares: 3 },
    ])
    expect(rows[1].shares).toBe(9)
  })
})
