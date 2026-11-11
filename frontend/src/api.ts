export type RunConfig = {
  tickers: string[]
  universe_file?: string | null
  start: string
  end: string
  benchmark: string | null
  strategy: { name: string; params: Record<string, unknown> }
  data: { provider: 'yfinance' | 'polygon' }
  execution: { cost_bps: number }
}

export type RunRecord = {
  run_id: string
  created_at: string
  review_state: 'draft' | 'reviewed' | 'superseded'
  config: RunConfig
  metrics: Record<string, number>
}

export type PaperInput = {
  target_weights: Record<string, number>
  prices: Record<string, number>
  as_of: string
}

export type PaperPayload = {
  target_weights: Record<string, number>
  prices: Record<string, number>
  holdings: Record<string, number>
  cash: number
  cost_bps: number
}

export type PaperResult = {
  trades: Array<{
    ticker: string
    current_shares: number
    target_shares: number
    delta_shares: number
    price: number
    estimated_cost: number
  }>
  starting_value: number
  ending_cash: number
  turnover: number
  estimated_cost: number
}

export type ScenarioRow = {
  scenario: string
  portfolio: string
  ticker: string
  contribution: number
  portfolio_shock: number
}

export type ComparisonRow = {
  portfolio: string
  observations: number
  cumulative_return: number
  max_drawdown: number
  annualized_volatility: number
  correlation_to_benchmark: number | null
  concentration: number
}

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, options)
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null)
    const detail = body && typeof body === 'object' && 'detail' in body ? body.detail : null
    throw new Error(typeof detail === 'string' ? detail : `Request failed (${response.status})`)
  }
  return response.json() as Promise<T>
}

export function jsonPost(payload: unknown): RequestInit {
  return {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }
}

export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.append(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}
