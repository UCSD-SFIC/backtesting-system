import { describe, expect, it } from 'vitest'
import { chartPoints, parseTickers, percent } from './format'

describe('dashboard input and display helpers', () => {
  it('normalizes entered tickers without duplicates', () => {
    expect(parseTickers('spy, sh  SPY')).toEqual(['SPY', 'SH'])
  })
  it('formats missing and finite percentages', () => {
    expect(percent(null)).toBe('—')
    expect(percent(0.1234)).toBe('12.3%')
  })
  it('makes chart points from a series', () => {
    expect(chartPoints([1, 2]).split(' ')).toHaveLength(2)
    expect(chartPoints([1])).toBe('')
  })
})
