import { useEffect, useMemo, useState } from 'react'
import {
  api, downloadBlob, jsonPost,
  type ComparisonRow, type PaperInput, type PaperPayload, type PaperResult,
  type RunConfig, type RunRecord, type ScenarioRow,
} from './api'
import { chartPoints, metricLabel, money, parseTickers, percent } from './format'
import { parseHoldingsCsv, replaceHoldingShares } from './holdings'

type Screen = 'backtests' | 'scenarios' | 'paper' | 'guide'
type Draft = {
  start: string; end: string; tickers: string; provider: 'yfinance' | 'polygon'
  cost: number; weights: Record<string, number>; rebalance: 'monthly' | 'quarterly'
  strategyParams: Record<string, number>
}
type AssetRow = { ticker: string; a: number; b: number; shock: number; shares: number }

const defaultDraft: Draft = {
  start: '2022-01-01', end: '2025-12-31', tickers: 'SPY, BND', provider: 'yfinance',
  cost: 0, weights: { SPY: 50, BND: 50 }, rebalance: 'monthly', strategyParams: {},
}

const templates: Record<string, { title: string; description: string; tag: string }> = {
  'fixed_weight.toml': { title: 'Build a portfolio', description: 'Choose asset percentages and a rebalance schedule.', tag: 'Portfolio' },
  'sma_crossover.toml': { title: 'Moving average crossover', description: 'Compare short and long price trends.', tag: 'Indicator' },
  'ema_dip.toml': { title: 'EMA dip', description: 'Test a dip signal within a longer trend.', tag: 'Indicator' },
}

function templateTitle(name: string): string {
  return templates[name]?.title ?? name.replace(/\.toml$/, '').replaceAll('_', ' ')
}

function draftFromConfig(config: RunConfig): Draft {
  const weights = config.strategy.params.weights as Record<string, number> | undefined
  return {
    start: config.start, end: config.end, tickers: config.tickers.join(', '),
    provider: config.data.provider, cost: config.execution.cost_bps,
    weights: Object.fromEntries(Object.entries(weights ?? {}).map(([ticker, value]) => [ticker, value * 100])),
    rebalance: config.strategy.params.rebalance === 'quarterly' ? 'quarterly' : 'monthly',
    strategyParams: Object.fromEntries(Object.entries(config.strategy.params)
      .filter(([, value]) => typeof value === 'number')) as Record<string, number>,
  }
}

function Numeric({ label, value, onChange, min = 0, max, step = 1 }: {
  label: string; value: number; onChange: (value: number) => void
  min?: number; max?: number; step?: number
}) {
  return <label className="field"><span>{label}</span><input type="number" value={value}
    min={min} max={max} step={step} onChange={event => onChange(Number(event.target.value))} /></label>
}

export function App() {
  const [screen, setScreen] = useState<Screen>('backtests')
  const [configs, setConfigs] = useState<string[]>([])
  const [configName, setConfigName] = useState('')
  const [config, setConfig] = useState<RunConfig | null>(null)
  const [loadedConfigName, setLoadedConfigName] = useState('')
  const [configLoading, setConfigLoading] = useState(false)
  const [configLoadVersion, setConfigLoadVersion] = useState(0)
  const [draft, setDraft] = useState<Draft>(defaultDraft)
  const [runs, setRuns] = useState<RunRecord[]>([])
  const [selected, setSelected] = useState<RunRecord | null>(null)
  const [equity, setEquity] = useState<number[]>([])
  const [paperInput, setPaperInput] = useState<PaperInput | null>(null)
  const [assets, setAssets] = useState<AssetRow[]>([])
  const [cash, setCash] = useState(10000)
  const [holdingsFilename, setHoldingsFilename] = useState('')
  const [scenarioName, setScenarioName] = useState('Market selloff')
  const [scenarioResults, setScenarioResults] = useState<ScenarioRow[]>([])
  const [comparison, setComparison] = useState<ComparisonRow[]>([])
  const [paperResult, setPaperResult] = useState<PaperResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    void Promise.all([api<{ configs: string[] }>('/api/configs'), api<{ runs: RunRecord[] }>('/api/runs')])
      .then(([available, saved]) => {
        setConfigs(available.configs)
        selectTemplate(available.configs.find(name => name === 'fixed_weight.toml') ?? available.configs[0] ?? '')
        setRuns(saved.runs)
      }).catch(reason => setError(String(reason)))
  }, [])

  useEffect(() => {
    if (!configName) return
    const controller = new AbortController()
    let active = true
    void api<{ config: RunConfig }>(`/api/configs/${encodeURIComponent(configName)}`, { signal: controller.signal })
      .then(response => {
        if (!active) return
        setConfig(response.config)
        setDraft(draftFromConfig(response.config))
        setLoadedConfigName(configName)
        setConfigLoading(false)
      })
      .catch(reason => {
        if (!active || controller.signal.aborted) return
        setError(reason instanceof Error ? reason.message : String(reason))
        setConfigLoading(false)
      })
    return () => { active = false; controller.abort() }
  }, [configName, configLoadVersion])

  useEffect(() => {
    if (!selected) return
    void api<{ growth: number[] }>(`/api/runs/${selected.run_id}/equity`)
      .then(curve => setEquity(curve.growth)).catch(reason => setError(String(reason)))
    void api<PaperInput>(`/api/runs/${selected.run_id}/paper-input`)
      .then(input => {
        setPaperInput(input)
        setAssets(Object.entries(input.target_weights).map(([ticker, weight]) => ({
          ticker, a: Math.round(weight * 100), b: Math.round(weight * 100),
          shock: -20, shares: 0,
        })))
      }).catch(() => { setPaperInput(null); setAssets([]) })
    setPaperResult(null); setScenarioResults([]); setComparison([])
    setHoldingsFilename('')
  }, [selected?.run_id])

  const benchmark = selected?.config.benchmark ?? selected?.config.tickers[0] ?? 'SPY'
  const activeAssets = assets.filter(row => row.ticker.trim())
  const totals = useMemo(() => ({
    a: activeAssets.reduce((sum, row) => sum + row.a, 0),
    b: activeAssets.reduce((sum, row) => sum + row.b, 0),
  }), [assets])

  function updateDraft<K extends keyof Draft>(key: K, value: Draft[K]) {
    setDraft(previous => ({ ...previous, [key]: value }))
  }
  function selectTemplate(name: string) {
    setConfigName(name)
    setConfig(null)
    setLoadedConfigName('')
    setDraft(defaultDraft)
    setConfigLoading(Boolean(name))
    setConfigLoadVersion(previous => previous + 1)
    setError('')
  }
  function updateAsset(index: number, changes: Partial<AssetRow>) {
    setAssets(previous => previous.map((row, i) => i === index ? { ...row, ...changes } : row))
    setPaperResult(null)
  }
  async function task(action: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('')
    try { await action() } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setBusy(false) }
  }
  async function launchRun(event: React.FormEvent) {
    event.preventDefault()
    if (!configName || !config || configLoading || loadedConfigName !== configName) return
    const tickers = parseTickers(draft.tickers)
    if (!tickers.length || draft.start >= draft.end) { setError('Choose tickers and a valid date range.'); return }
    const weights = Object.fromEntries(tickers.map(ticker => [ticker, draft.weights[ticker] ?? 0]))
    if (config.strategy.name === 'fixed_weight' && Math.abs(Object.values(weights).reduce((sum, weight) => sum + weight, 0) - 100) > 0.001) {
      setError('Portfolio target weights must total 100%.'); return
    }
    const windowNames = config.strategy.name === 'sma_crossover' ? ['short_window', 'long_window'] :
      config.strategy.name === 'ema_dip' ? ['ema_window', 'regime_window'] : []
    if (windowNames.length) {
      const [short, long] = windowNames.map(name => draft.strategyParams[name])
      if (!Number.isInteger(short) || !Number.isInteger(long) || short < 1 || long < 1 || short >= long) {
        setError('Indicator windows must be positive whole numbers; the first must be shorter than the second.'); return
      }
    }
    await task(async () => {
      const overrides: Record<string, unknown> = {
        start: draft.start, end: draft.end,
        provider: draft.provider, cost_bps: draft.cost,
      }
      overrides.tickers = tickers
      if (config.strategy.name === 'fixed_weight') Object.assign(overrides, {
        target_weights: Object.fromEntries(Object.entries(weights).map(([ticker, value]) => [ticker, value / 100])),
        rebalance: draft.rebalance,
      })
      if (config.strategy.name === 'sma_crossover' || config.strategy.name === 'ema_dip') {
        overrides.strategy_params = draft.strategyParams
      }
      const created = await api<{ run_id: string }>('/api/runs', jsonPost({ config_name: configName, overrides }))
      const [record, listing] = await Promise.all([
        api<RunRecord>(`/api/runs/${created.run_id}`), api<{ runs: RunRecord[] }>('/api/runs'),
      ])
      setRuns(listing.runs); setSelected(record); setNotice('Backtest completed and saved.')
    })
  }
  async function updateReview(value: RunRecord['review_state']) {
    if (!selected) return
    await task(async () => {
      const updated = await api<RunRecord>(`/api/runs/${selected.run_id}/review`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ state: value }),
      })
      setSelected(updated)
      setRuns(previous => previous.map(run => run.run_id === updated.run_id ? updated : run))
      setNotice('Review state saved.')
    })
  }
  function portfolios(): Record<string, Record<string, number>> {
    if (totals.a <= 0 || totals.b <= 0 || totals.a > 100 || totals.b > 100) {
      throw new Error('Each portfolio must have weights totaling between 1% and 100%.')
    }
    return {
      'Portfolio A': Object.fromEntries(activeAssets.filter(row => row.a > 0).map(row => [row.ticker, row.a / 100])),
      'Portfolio B': Object.fromEntries(activeAssets.filter(row => row.b > 0).map(row => [row.ticker, row.b / 100])),
    }
  }
  async function runScenarios() {
    await task(async () => {
      const selectedPortfolios = portfolios()
      const shocks = Object.fromEntries(activeAssets.map(row => [row.ticker, row.shock / 100]))
      const response = await api<{ results: ScenarioRow[] }>('/api/scenarios',
        jsonPost({ portfolios: selectedPortfolios, shocks: { [scenarioName || 'Custom scenario']: shocks } }))
      setScenarioResults(response.results)
      setNotice('Scenario sensitivity calculated.')
    })
  }
  async function compareHistory() {
    if (!selected) { setError('Select a saved run first.'); return }
    await task(async () => {
      const response = await api<{ results: ComparisonRow[] }>(`/api/runs/${selected.run_id}/compare`,
        jsonPost({ benchmark, portfolios: portfolios() }))
      setComparison(response.results)
      setNotice('Historical portfolio comparison calculated.')
    })
  }
  function paperPayload(): PaperPayload {
    if (!paperInput) throw new Error('Select a saved run with target holdings first.')
    const missingPrices = activeAssets.filter(row => row.shares > 0 && !(row.ticker in paperInput.prices))
    if (missingPrices.length) throw new Error(`Latest price missing for: ${missingPrices.map(row => row.ticker).join(', ')}`)
    return {
      target_weights: paperInput.target_weights,
      prices: paperInput.prices,
      holdings: Object.fromEntries(activeAssets.filter(row => row.ticker in paperInput.prices).map(row => [row.ticker, row.shares])),
      cash, cost_bps: selected?.config.execution.cost_bps ?? 0,
    }
  }
  async function importHoldings(file: File | undefined) {
    if (!file || !paperInput) return
    setError('')
    try {
      if (file.size > 1_000_000) throw new Error('Holdings CSV must be under 1 MB.')
      const holdings = parseHoldingsCsv(await file.text())
      const missingPrices = Object.keys(holdings).filter(ticker => !(ticker in paperInput.prices))
      if (missingPrices.length) throw new Error(`Latest price missing for: ${missingPrices.join(', ')}`)
      setAssets(previous => replaceHoldingShares(previous, holdings, (ticker, shares) => ({
        ticker, a: 0, b: 0, shock: -20, shares,
      })))
      setPaperResult(null)
      setHoldingsFilename(file.name)
      setNotice(`Imported ${Object.keys(holdings).length} holdings from CSV.`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    }
  }
  async function calculatePaper() {
    await task(async () => {
      const result = await api<PaperResult>('/api/paper-rebalance', jsonPost(paperPayload()))
      setPaperResult(result)
      setNotice('Paper rebalance calculated. Review changes before downloading.')
    })
  }
  async function downloadPaper() {
    await task(async () => {
      const response = await fetch('/api/paper-rebalance.csv', jsonPost(paperPayload()))
      if (!response.ok) throw new Error('Could not create paper packet.')
      downloadBlob(await response.blob(), 'paper-rebalance.csv')
      setNotice('Paper packet downloaded.')
    })
  }

  return <div className="app-shell">
    <header className="topbar">
      <div className="topbar-logo">SFIC <span>PORTFOLIO LAB</span></div>
      <div className="topbar-actions"><span className="topbar-status"><span className="status-dot" /> LOCAL RESEARCH</span><button className="topbar-help" onClick={() => setScreen('guide')}>How it works <span aria-hidden="true">↗</span></button></div>
    </header>
    <aside className="sidebar">
      <p className="sidebar-caption">RESEARCH WORKSPACE</p>
      <nav aria-label="Main navigation">
        <button className={screen === 'backtests' ? 'nav-active' : ''} onClick={() => setScreen('backtests')}>↗ <span>Backtests</span></button>
        <button className={screen === 'scenarios' ? 'nav-active' : ''} onClick={() => setScreen('scenarios')}>◫ <span>Scenarios</span></button>
        <button className={screen === 'paper' ? 'nav-active' : ''} onClick={() => setScreen('paper')}>▤ <span>Paper rebalance</span></button>
        <button className={screen === 'guide' ? 'nav-active' : ''} onClick={() => setScreen('guide')}>ⓘ <span>Guide &amp; TOML</span></button>
      </nav>
      <div className="sidebar-foot">HISTORICAL SIMULATION<br /><small>Research and paper portfolios</small></div>
    </aside>
    <main className="content">
      <header className="page-header">
        <div><p className="eyebrow">SFIC · RESEARCH TERMINAL</p><h1>{screen === 'backtests' ? 'Backtest lab' : screen === 'scenarios' ? 'Scenario studio' : screen === 'paper' ? 'Paper rebalance' : 'How this works'}</h1>
          <p className="subheading">{screen === 'backtests' ? 'Configure an idea, run it on past data, and inspect the evidence.' : screen === 'scenarios' ? 'Explore portfolio combinations and market stress.' : screen === 'paper' ? 'Turn target weights into a reviewable paper recommendation.' : 'A quick guide to templates, TOML, and the research workflow.'}</p></div>
        <span className="badge">RESEARCH · NO LIVE TRADING</span>
      </header>
      {error && <div role="alert" className="message error">{error}<button aria-label="Dismiss error" onClick={() => setError('')}>×</button></div>}
      {notice && <div role="status" className="message success">{notice}<button aria-label="Dismiss message" onClick={() => setNotice('')}>×</button></div>}

      {screen === 'backtests' && <>
        <div className="step-strip" aria-label="Backtest workflow"><span className="step-current"><b>1</b> Configure</span><span className="step-divider">→</span><span><b>2</b> Run</span><span className="step-divider">→</span><span><b>3</b> Analyze</span></div>
        <div className="workspace-grid">
          <section className="card setup-card"><div className="card-header"><div><p className="eyebrow">01 / CONFIGURE</p><h2>New backtest</h2></div></div>
            <form onSubmit={launchRun} className="form-stack">
              <div><p className="field-heading">Choose an idea</p><div className="template-list" role="group" aria-label="Strategy templates">{configs.map(name => <button type="button" key={name} className={`template-option ${configName === name ? 'template-selected' : ''}`} aria-pressed={configName === name} onClick={() => selectTemplate(name)}><span className="template-top"><strong>{templateTitle(name)}</strong><small>{templates[name]?.tag ?? 'Template'}</small></span><span className="template-description">{templates[name]?.description ?? 'Load this saved configuration.'}</span></button>)}</div><p className="field-note">Templates supply starting values. Changes here apply to this run; the TOML file stays unchanged. <button type="button" className="inline-link" onClick={() => setScreen('guide')}>What is TOML?</button></p></div>
              <div className="form-divider"><span>Market &amp; period</span></div>
              <div className="two-columns"><label className="field"><span>Start date</span><input type="date" required value={draft.start} onChange={event => updateDraft('start', event.target.value)} /></label><label className="field"><span>End date</span><input type="date" required value={draft.end} onChange={event => updateDraft('end', event.target.value)} /></label></div>
              {config && <p className="field-note">Price interval: <strong>{config.timespan}</strong> (from this template). Edit its TOML file to change the interval.</p>}
              <label className="field"><span>Assets <small>ticker symbols, comma separated</small></span><input value={draft.tickers} onChange={event => updateDraft('tickers', event.target.value)} placeholder="SPY, BND" /></label>
              <div className="two-columns"><label className="field"><span>Price data</span><select value={draft.provider} onChange={event => updateDraft('provider', event.target.value as Draft['provider'])}><option value="yfinance">Yahoo Finance · default</option><option value="polygon">Polygon · API key needed</option></select></label><Numeric label="Simulated cost (bps)" value={draft.cost} max={500} step={0.1} onChange={value => updateDraft('cost', value)} /></div>
              <p className="field-note">One basis point is 0.01%. Cost is applied to simulated turnover; 0 disables it.</p>
              {config?.strategy.name === 'fixed_weight' && <div className="portfolio-fields">
                <p className="field-heading">Target portfolio weights</p>
                <p className="helper">Set a percentage for each ticker. The total must be 100%.</p>
                <div className="weight-grid">{parseTickers(draft.tickers).map(ticker => <Numeric key={ticker} label={`${ticker} %`} value={draft.weights[ticker] ?? 0} max={100} step={0.1} onChange={value => setDraft(previous => ({ ...previous, weights: { ...previous.weights, [ticker]: value } }))} />)}</div>
                <div className="weight-total">Total: {parseTickers(draft.tickers).reduce((sum, ticker) => sum + (draft.weights[ticker] ?? 0), 0).toFixed(1)}%</div>
                <label className="field"><span>Rebalance frequency</span><select value={draft.rebalance} onChange={event => updateDraft('rebalance', event.target.value as Draft['rebalance'])}><option value="monthly">Monthly</option><option value="quarterly">Quarterly</option></select></label>
              </div>}
              {(config?.strategy.name === 'sma_crossover' || config?.strategy.name === 'ema_dip') && <div className="portfolio-fields"><p className="field-heading">Indicator settings</p><p className="field-note">Windows count historical price bars. Longer windows react more slowly.</p><div className="two-columns">{(config.strategy.name === 'sma_crossover' ? [['short_window', 'Short average'], ['long_window', 'Long average']] : [['ema_window', 'Dip average'], ['regime_window', 'Trend average']]).map(([key, label]) => <Numeric key={key} label={`${label} · bars`} value={draft.strategyParams[key] ?? 1} min={1} max={1000} onChange={value => setDraft(previous => ({ ...previous, strategyParams: { ...previous.strategyParams, [key]: value } }))} />)}</div></div>}
              <button className="primary run-button" disabled={busy || !configName || configLoading || loadedConfigName !== configName} type="submit">{busy ? 'Running on historical data…' : configLoading ? 'Loading template…' : 'Run backtest'} <span aria-hidden="true">→</span></button>
              <p className="field-note">The run is saved locally so you can inspect it again.</p>
            </form>
          </section>
          <section className="card saved-card"><div className="card-header"><div><p className="eyebrow">RECENT SESSIONS</p><h2>Saved runs</h2></div><span className="count">{runs.length}</span></div>
            <div className="run-list">{runs.length ? runs.map(run => <button key={run.run_id} className={`run-item ${selected?.run_id === run.run_id ? 'selected' : ''}`} onClick={() => setSelected(run)}><span><strong>{run.config.strategy?.name?.replaceAll('_', ' ') ?? 'Backtest'}</strong><small>{run.config.start} → {run.config.end}</small></span><span className="run-side"><b className={run.metrics.total_return < 0 ? 'value-negative' : 'value-positive'}>{percent(run.metrics.total_return)}</b><small>{run.review_state}</small></span></button>) : <p className="empty">No saved runs yet. Start with a strategy template.</p>}</div>
          </section>
        <section className="card results-card"><div className="card-header"><div><p className="eyebrow">03 / ANALYZE</p><h2>{selected ? 'Performance overview' : 'Your results will appear here'}</h2></div>{selected && <span className="soft-tag">{selected.run_id.slice(0, 8)}</span>}</div>
          {selected ? <><div className="metric-grid">{['total_return', 'compounding_annual_return', 'sharpe_ratio', 'sortino_ratio', 'max_drawdown', 'annualized_volatility'].map(key => <div className="metric" key={key}><small>{metricLabel(key)}</small><strong className={key === 'annualized_volatility' ? undefined : selected.metrics[key] < 0 ? 'value-negative' : 'value-positive'}>{['sharpe_ratio', 'sortino_ratio'].includes(key) ? (selected.metrics[key]?.toFixed(2) ?? '—') : percent(selected.metrics[key])}</strong></div>)}</div>
            <div className="chart-wrap"><div className="chart-heading"><h3>Portfolio growth</h3><small>Historical simulation</small></div><svg viewBox="0 0 760 210" role="img" aria-label="Portfolio growth curve"><line className="chart-axis" x1="12" y1="198" x2="748" y2="198" /><polyline className="chart-line" points={chartPoints(equity)} fill="none" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" /></svg></div>
            <div className="result-actions"><label className="field compact"><span>Review state</span><select value={selected.review_state} onChange={event => void updateReview(event.target.value as RunRecord['review_state'])}><option value="draft">Draft</option><option value="reviewed">Reviewed</option><option value="superseded">Superseded</option></select></label><button className="secondary" onClick={() => setScreen('scenarios')}>Explore scenarios →</button><button className="secondary" onClick={() => setScreen('paper')}>Paper rebalance →</button></div>
          </> : <div className="result-empty"><div className="result-empty-graphic" aria-hidden="true"><span /><span /><span /><span /><span /></div><h3>Start with a backtest</h3><p>Choose a template, set your assets and dates, then run it. This space will show the growth curve and risk metrics. You can also reopen any saved run below.</p></div>}</section>
        </div>
      </>}

      {screen === 'scenarios' && <>
        {!runs.length && <div className="next-step-notice"><div><strong>Testing a new portfolio?</strong><span>Add assets below to model a price shock. Run a backtest first if you also want a historical comparison.</span></div><button className="secondary" onClick={() => setScreen('backtests')}>Create backtest →</button></div>}
        <RunPicker runs={runs} selected={selected} onSelect={setSelected} />
        <section className="card"><div className="card-header"><div><p className="eyebrow">01 / ASSUMPTIONS</p><h2>Compare two portfolios</h2></div><span className="soft-tag">Fixed-weight research</span></div>
          <p className="helper">Set each asset’s share in two candidate portfolios. Enter a one-period shock to see how each combination responds. This is research, not a forecast.</p>
          <label className="field scenario-name"><span>Scenario name</span><input value={scenarioName} maxLength={80} onChange={event => setScenarioName(event.target.value)} /></label>
          <div className="table-scroll"><table><thead><tr><th>Asset</th><th>Portfolio A %</th><th>Portfolio B %</th><th>Shock %</th><th></th></tr></thead><tbody>{assets.map((row, index) => <tr key={index}><td><input aria-label={`Asset ${index + 1} ticker`} value={row.ticker} onChange={event => updateAsset(index, { ticker: event.target.value.toUpperCase() })} /></td><td><input aria-label={`${row.ticker} portfolio A weight`} type="number" min="0" max="100" value={row.a} onChange={event => updateAsset(index, { a: Number(event.target.value) })} /></td><td><input aria-label={`${row.ticker} portfolio B weight`} type="number" min="0" max="100" value={row.b} onChange={event => updateAsset(index, { b: Number(event.target.value) })} /></td><td><input aria-label={`${row.ticker} scenario shock`} type="number" min="-100" step="0.1" value={row.shock} onChange={event => updateAsset(index, { shock: Number(event.target.value) })} /></td><td><button aria-label={`Remove ${row.ticker}`} className="icon-button" onClick={() => setAssets(previous => previous.filter((_, i) => i !== index))}>×</button></td></tr>)}</tbody><tfoot><tr><td>Total</td><td>{totals.a}%</td><td>{totals.b}%</td><td></td><td></td></tr></tfoot></table></div>
          <button className="text-button" onClick={() => setAssets(previous => [...previous, { ticker: '', a: 0, b: 0, shock: 0, shares: 0 }])}>+ Add asset</button>
          <div className="action-row"><button className="primary" disabled={busy || !activeAssets.length} onClick={() => void runScenarios()}>Calculate sensitivity</button><button className="secondary" disabled={busy || !selected} onClick={() => void compareHistory()}>Compare historical returns</button></div>
          {!selected && <p className="helper">Select a saved run to compare against its historical prices.</p>}
        </section>
        {scenarioResults.length > 0 && <section className="card"><div className="card-header"><div><p className="eyebrow">02 / SCENARIO OUTPUT</p><h2>Assumed shock results</h2></div></div><div className="summary-grid">{[...new Map(scenarioResults.map(row => [row.portfolio, row.portfolio_shock])).entries()].map(([name, value]) => <div className="summary-tile" key={name}><small>{name}</small><strong>{percent(value)}</strong></div>)}</div><div className="table-scroll"><table><thead><tr><th>Portfolio</th><th>Asset</th><th>Contribution</th></tr></thead><tbody>{scenarioResults.map((row, index) => <tr key={index}><td>{row.portfolio}</td><td>{row.ticker}</td><td>{percent(row.contribution)}</td></tr>)}</tbody></table></div></section>}
        {comparison.length > 0 && <section className="card"><div className="card-header"><div><p className="eyebrow">03 / HISTORICAL OUTPUT</p><h2>Portfolio comparison</h2></div></div><p className="helper">Fixed weights reset each bar. Trading costs are excluded.</p><div className="table-scroll"><table><thead><tr><th>Portfolio</th><th>Return</th><th>Drawdown</th><th>Volatility</th><th>Market correlation</th><th>Concentration</th></tr></thead><tbody>{comparison.map(row => <tr key={row.portfolio}><td>{row.portfolio}</td><td>{percent(row.cumulative_return)}</td><td>{percent(row.max_drawdown)}</td><td>{percent(row.annualized_volatility)}</td><td>{row.correlation_to_benchmark?.toFixed(2) ?? '—'}</td><td>{row.concentration.toFixed(2)}</td></tr>)}</tbody></table></div></section>}
      </>}

      {screen === 'paper' && <>{!runs.length && <div className="next-step-notice"><div><strong>Start with a portfolio backtest</strong><span>Paper rebalance needs the target weights and latest prices from a saved fixed-weight run.</span></div><button className="secondary" onClick={() => setScreen('backtests')}>Create backtest →</button></div>}<RunPicker runs={runs} selected={selected} onSelect={setSelected} /><section className="card"><div className="card-header"><div><p className="eyebrow">01 / PORTFOLIO</p><h2>Current paper holdings</h2></div><span className="soft-tag">Whole shares</span></div>
        {paperInput ? <><p className="helper">Target weights and latest prices come from your saved run. Enter shares and cash, or import a ticker,shares CSV.</p><label className="upload-field"><span>Import paper holdings CSV</span><input aria-label="Import paper holdings CSV" type="file" accept=".csv,text/csv" onChange={event => void importHoldings(event.target.files?.[0])} /><small>{holdingsFilename || 'ticker,shares columns · up to 1 MB'}</small></label><div className="table-scroll"><table><thead><tr><th>Asset</th><th>Target weight</th><th>Latest price</th><th>Current shares</th></tr></thead><tbody>{assets.map((row, index) => <tr key={index}><td><strong>{row.ticker}</strong></td><td>{percent(paperInput.target_weights[row.ticker] ?? 0)}</td><td>{money(paperInput.prices[row.ticker] ?? 0)}</td><td><input aria-label={`${row.ticker} current shares`} type="number" min="0" step="1" value={row.shares} onChange={event => updateAsset(index, { shares: Number(event.target.value) })} /></td></tr>)}</tbody></table></div><div className="paper-actions"><Numeric label="Available cash" value={cash} step={0.01} onChange={value => { setCash(value); setPaperResult(null) }} /><button className="primary" disabled={busy} onClick={() => void calculatePaper()}>Calculate paper rebalance</button></div></> : <p className="empty">Select a saved fixed-weight run to populate target weights and prices.</p>}
      </section>{paperResult && <section className="card"><div className="card-header"><div><p className="eyebrow">02 / RECOMMENDATION</p><h2>Review share changes</h2></div><span className="soft-tag">Paper only</span></div><div className="summary-grid"><div className="summary-tile"><small>Starting value</small><strong>{money(paperResult.starting_value)}</strong></div><div className="summary-tile"><small>Leftover cash</small><strong>{money(paperResult.ending_cash)}</strong></div><div className="summary-tile"><small>Estimated cost</small><strong>{money(paperResult.estimated_cost)}</strong></div></div><div className="table-scroll"><table><thead><tr><th>Asset</th><th>Current</th><th>Target</th><th>Paper change</th><th>Estimated cost</th></tr></thead><tbody>{paperResult.trades.map(trade => <tr key={trade.ticker}><td>{trade.ticker}</td><td>{trade.current_shares}</td><td>{trade.target_shares}</td><td><span className={trade.delta_shares > 0 ? 'buy' : trade.delta_shares < 0 ? 'sell' : ''}>{trade.delta_shares > 0 ? `+${trade.delta_shares}` : trade.delta_shares}</span></td><td>{money(trade.estimated_cost)}</td></tr>)}</tbody></table></div><button className="primary" disabled={busy} onClick={() => void downloadPaper()}>Download paper packet CSV ↓</button><p className="helper">This is a simulation for review; no order is sent.</p></section>}</>}
      {screen === 'guide' && <div className="guide-layout"><section className="card guide-intro"><p className="eyebrow">START HERE</p><h2>From idea to evidence</h2><p>Use the browser for routine research. Pick a template, adjust its settings, and run it against historical prices. The app saves each result locally so you can compare ideas or reopen a run later.</p><div className="system-flow" aria-label="How the app processes a backtest"><span>Browser</span><span>Python API</span><span>Price data</span><span>Strategy</span><span>Engine</span><span>Results</span></div><div className="guide-steps"><div><b>1</b><strong>Configure</strong><span>Choose a strategy, assets, dates, and assumptions.</span></div><div><b>2</b><strong>Run</strong><span>The Python backend fetches prices and simulates portfolio weights over time.</span></div><div><b>3</b><strong>Review</strong><span>Read the growth chart, return and risk metrics, then test scenarios.</span></div></div><button className="primary" onClick={() => setScreen('backtests')}>Create a backtest →</button></section><section className="card"><p className="eyebrow">THE CONFIG FILE</p><h2>What is TOML?</h2><p className="helper">TOML is a readable settings file. Each template in <code>configs/</code> gives the app starting values. The fields you edit in the dashboard override those values for one run; they do not rewrite the file.</p><pre className="toml-example"><code>{`tickers = ["SPY", "BND"]
start = 2024-01-01
end = 2024-12-31

[strategy]
name = "fixed_weight"

[strategy.params]
weights = { SPY = 0.5, BND = 0.5 }
rebalance = "monthly"

[data]
provider = "yfinance"`}</code></pre><div className="guide-glossary"><div><strong>tickers</strong><span>Assets whose price history is loaded.</span></div><div><strong>start / end</strong><span>The historical test period.</span></div><div><strong>strategy</strong><span>The rule that chooses portfolio weights.</span></div><div><strong>weights</strong><span>Decimal fractions: 0.5 means 50%; together they total 1.0.</span></div><div><strong>provider</strong><span>Where the price history comes from.</span></div></div></section><section className="card guide-span"><p className="eyebrow">AFTER THE RUN</p><h2>Where to go next</h2><div className="guide-next"><div><strong>Scenarios</strong><p>Set assumed price shocks and compare two candidate portfolios. A saved run supplies historical prices for the comparison.</p><button className="secondary" onClick={() => setScreen('scenarios')}>Open scenarios →</button></div><div><strong>Paper rebalance</strong><p>For a fixed-weight run, enter current shares and cash. The app calculates simulated share changes and a downloadable CSV.</p><button className="secondary" onClick={() => setScreen('paper')}>Open paper rebalance →</button></div></div><p className="helper guide-footnote">To create an entirely new strategy type, write a Python <code>Alpha</code> implementation, register it, and add a TOML template. See the repository README for developer steps.</p></section></div>}
    </main>
  </div>
}

function RunPicker({ runs, selected, onSelect }: {
  runs: RunRecord[]; selected: RunRecord | null; onSelect: (run: RunRecord | null) => void
}) {
  return <section className="card picker"><label className="field"><span>Use a saved backtest</span><select value={selected?.run_id ?? ''} onChange={event => onSelect(runs.find(run => run.run_id === event.target.value) ?? null)}><option value="">Choose a run</option>{runs.map(run => <option value={run.run_id} key={run.run_id}>{run.config.strategy?.name} · {run.config.start} · {run.run_id.slice(0, 8)}</option>)}</select></label><small>Run a strategy in Backtests first to populate its holdings and prices.</small></section>
}
