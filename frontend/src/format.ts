export function percent(value: number | null | undefined, digits = 1): string {
  return value == null || !Number.isFinite(value) ? '—' : `${(value * 100).toFixed(digits)}%`
}

export function money(value: number): string {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(value)
}

export function parseTickers(value: string): string[] {
  return [...new Set(value.split(/[\s,]+/).map(ticker => ticker.trim().toUpperCase()).filter(Boolean))]
}

export function metricLabel(key: string): string {
  return key.replaceAll('_', ' ').replace(/^./, letter => letter.toUpperCase())
}

export function chartPoints(values: number[], width = 760, height = 210): string {
  const finite = values.filter(Number.isFinite)
  if (finite.length < 2) return ''
  const min = Math.min(...finite)
  const max = Math.max(...finite)
  const span = max - min || 1
  return values.map((value, index) => {
    const x = 12 + index / Math.max(values.length - 1, 1) * (width - 24)
    const y = height - 12 - (value - min) / span * (height - 24)
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
}
