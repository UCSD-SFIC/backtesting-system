import { useEffect, useMemo, useState } from 'react'
import {
  api, downloadBlob, jsonPost,
  type ComparisonRow, type PaperInput, type PaperPayload, type PaperResult,
  type RunConfig, type RunRecord, type ScenarioRow,
} from './api'
import { chartPoints, metricLabel, money, parseTickers, percent } from './format'
import { parseHoldingsCsv, replaceHoldingShares } from './holdings'

type Screen = 'backtests' | 'scenarios' | 'paper'
type Draft = {
  start: string; end: string; tickers: string; provider: 'yfinance' | 'polygon'
  cost: number; momentum: number; high: number; momentumCount: number
  highCount: number; rebalance: 'monthly' | 'quarterly'
}
type AssetRow = { ticker: string; a: number; b: number; shock: number; shares: number }

const defaultDraft: Draft = {
  start: '2022-01-01', end: '2025-12-31', tickers: 'SPY, SH', provider: 'yfinance',
  cost: 10, momentum: 30, high: 70, momentumCount: 20, highCount: 10,
  rebalance: 'monthly',
}

function draftFromConfig(config: RunConfig): Draft {
  const sleeves = config.strategy.params.sleeves as Record<string, number> | undefined
  const counts = config.strategy.params.sleeve_top_n as Record<string, number> | undefined
  return {
    start: config.start, end: config.end, tickers: config.tickers.join(', '),
    provider: config.data.provider, cost: config.execution.cost_bps,
    momentum: Math.round((sleeves?.momentum ?? 0.7) * 100),
    high: Math.round((sleeves?.high_52_week ?? 0.3) * 100),
    momentumCount: counts?.momentum ?? Number(config.strategy.params.top_n ?? 10),
    highCount: counts?.high_52_week ?? Number(config.strategy.params.top_n ?? 10),
    rebalance: config.strategy.params.rebalance === 'quarterly' ? 'quarterly' : 'monthly',
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
  const [trainSize, setTrainSize] = useState(252)
  const [testSize, setTestSize] = useState(63)
  const [walkForward, setWalkForward] = useState<{
    summary: Record<string, string | number>
    folds: Array<{ selected: string; train_return: number; test_return: number; train_end: string; test_begin: string }>
    candidates: Array<Record<string, string | number>>
  } | null>(null)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    void Promise.all([api<{ configs: string[] }>('/api/configs'), api<{ runs: RunRecord[] }>('/api/runs')])
      .then(([available, saved]) => {
        setConfigs(available.configs)
        setConfigName(available.configs[0] ?? '')
        setRuns(saved.runs)
      }).catch(reason => setError(String(reason)))
  }, [])

  useEffect(() => {
    if (!configName) return
    void api<{ config: RunConfig }>(`/api/configs/${encodeURIComponent(configName)}`)
      .then(response => { setConfig(response.config); setDraft(draftFromConfig(response.config)) })
      .catch(reason => setError(String(reason)))
  }, [configName])

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
    setPaperResult(null); setScenarioResults([]); setComparison([]); setWalkForward(null)
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
    if (!configName || !config) return
    const tickers = parseTickers(draft.tickers)
    if (!tickers.length || draft.start >= draft.end) { setError('Choose tickers and a valid date range.'); return }
    if (config.strategy.name === 'allocation' && draft.momentum + draft.high !== 100) {
      setError('The two strategy sleeve percentages must total 100%.'); return
    }
    await task(async () => {
      const overrides: Record<string, unknown> = {
        start: draft.start, end: draft.end,
        provider: draft.provider, cost_bps: draft.cost,
      }
      if (!config.universe_file) overrides.tickers = tickers
      if (config.strategy.name === 'allocation') Object.assign(overrides, {
        momentum_weight: draft.momentum / 100, high_weight: draft.high / 100,
        momentum_top_n: draft.momentumCount, high_top_n: draft.highCount,
        rebalance: draft.rebalance,
      })
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
  async function studyOutOfSample() {
    if (!selected) return
    await task(async () => {
      const result = await api<typeof walkForward>(`/api/runs/${selected.run_id}/walk-forward`,
        jsonPost({ train_size: trainSize, test_size: testSize }))
      setWalkForward(result)
      setNotice('Out of sample study completed.')
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
    <aside className="sidebar">
      <div className="brand"><span className="brand-mark">S</span><span>SFIC<span className="brand-muted"> / Portfolio Lab</span></span></div>
      <p className="sidebar-caption">RESEARCH WORKSPACE</p>
      <nav aria-label="Main navigation">
        <button className={screen === 'backtests' ? 'nav-active' : ''} onClick={() => setScreen('backtests')}>↗ <span>Backtests</span></button>
        <button className={screen === 'scenarios' ? 'nav-active' : ''} onClick={() => setScreen('scenarios')}>◫ <span>Scenarios</span></button>
        <button className={screen === 'paper' ? 'nav-active' : ''} onClick={() => setScreen('paper')}>▤ <span>Paper rebalance</span></button>
      </nav>
      <div className="sidebar-foot"><span className="status-dot" /> Local research app<br /><small>Historical simulation · paper only</small></div>
    </aside>
    <main className="content">
      <header className="page-header">
        <div><p className="eyebrow">SFIC QUANT RESEARCH</p><h1>{screen === 'backtests' ? 'Backtest workspace' : screen === 'scenarios' ? 'Scenario studio' : 'Paper rebalance'}</h1>
          <p className="subheading">{screen === 'backtests' ? 'Test allocation ideas and keep every result.' : screen === 'scenarios' ? 'Explore portfolio combinations and market stress.' : 'Turn target weights into a reviewable paper recommendation.'}</p></div>
        <span className="badge">RESEARCH · NO LIVE TRADING</span>
      </header>
      {error && <div role="alert" className="message error">{error}<button aria-label="Dismiss error" onClick={() => setError('')}>×</button></div>}
      {notice && <div role="status" className="message success">{notice}<button aria-label="Dismiss message" onClick={() => setNotice('')}>×</button></div>}

      {screen === 'backtests' && <>
        <div className="workspace-grid">
          <section className="card"><div className="card-header"><div><p className="eyebrow">01 / SETUP</p><h2>New backtest</h2></div><span className="soft-tag">Configured run</span></div>
            <form onSubmit={launchRun} className="form-stack">
              <label className="field"><span>Strategy template</span><select value={configName} onChange={event => setConfigName(event.target.value)}>{configs.map(name => <option key={name}>{name}</option>)}</select></label>
              <div className="two-columns"><label className="field"><span>Start date</span><input type="date" required value={draft.start} onChange={event => updateDraft('start', event.target.value)} /></label><label className="field"><span>End date</span><input type="date" required value={draft.end} onChange={event => updateDraft('end', event.target.value)} /></label></div>
              <label className="field"><span>Tickers {config?.universe_file ? <small>from saved universe</small> : <small>comma separated</small>}</span><input value={draft.tickers} readOnly={Boolean(config?.universe_file)} onChange={event => updateDraft('tickers', event.target.value)} placeholder="SPY, SH, AAPL" /></label>
              <div className="two-columns"><label className="field"><span>Data source</span><select value={draft.provider} onChange={event => updateDraft('provider', event.target.value as Draft['provider'])}><option value="yfinance">yfinance</option><option value="polygon">Polygon</option></select></label><Numeric label="Trading cost · bps" value={draft.cost} max={500} step={0.1} onChange={value => updateDraft('cost', value)} /></div>
              {config?.strategy.name === 'allocation' && <div className="allocation-fields"><p className="field-heading">Allocation sleeves</p><div className="two-columns"><Numeric label="Momentum %" value={draft.momentum} max={100} onChange={value => updateDraft('momentum', value)} /><Numeric label="52-week high %" value={draft.high} max={100} onChange={value => updateDraft('high', value)} /></div><div className="two-columns"><Numeric label="Momentum stocks" value={draft.momentumCount} min={1} onChange={value => updateDraft('momentumCount', value)} /><Numeric label="52-week high stocks" value={draft.highCount} min={1} onChange={value => updateDraft('highCount', value)} /></div><label className="field"><span>Rebalance frequency</span><select value={draft.rebalance} onChange={event => updateDraft('rebalance', event.target.value as Draft['rebalance'])}><option value="monthly">Monthly</option><option value="quarterly">Quarterly</option></select></label></div>}
              <button className="primary" disabled={busy || !configName} type="submit">{busy ? 'Running backtest…' : 'Run backtest'} <span aria-hidden="true">→</span></button>
            </form>
          </section>
          <section className="card saved-card"><div className="card-header"><div><p className="eyebrow">02 / HISTORY</p><h2>Saved runs</h2></div><span className="count">{runs.length}</span></div>
            <div className="run-list">{runs.length ? runs.map(run => <button key={run.run_id} className={`run-item ${selected?.run_id === run.run_id ? 'selected' : ''}`} onClick={() => setSelected(run)}><span><strong>{run.config.strategy?.name?.replaceAll('_', ' ') ?? 'Backtest'}</strong><small>{run.config.start} → {run.config.end}</small></span><span className="run-side"><b>{percent(run.metrics.total_return)}</b><small>{run.review_state}</small></span></button>) : <p className="empty">No saved runs yet. Start with a strategy template.</p>}</div>
          </section>
        </div>
        <section className="card results-card"><div className="card-header"><div><p className="eyebrow">03 / RESULTS</p><h2>{selected ? 'Run analysis' : 'Choose a saved run'}</h2></div>{selected && <span className="soft-tag">{selected.run_id.slice(0, 8)}</span>}</div>
          {selected ? <><div className="metric-grid">{['total_return', 'compounding_annual_return', 'sharpe_ratio', 'sortino_ratio', 'max_drawdown', 'annualized_volatility'].map(key => <div className="metric" key={key}><small>{metricLabel(key)}</small><strong>{['sharpe_ratio', 'sortino_ratio'].includes(key) ? (selected.metrics[key]?.toFixed(2) ?? '—') : percent(selected.metrics[key])}</strong></div>)}</div>
            <div className="chart-wrap"><div className="chart-heading"><h3>Portfolio growth</h3><small>Historical simulation</small></div><svg viewBox="0 0 760 210" role="img" aria-label="Portfolio growth curve"><line x1="12" y1="198" x2="748" y2="198" stroke="#d9e3df" /><polyline points={chartPoints(equity)} fill="none" stroke="#0f775e" strokeWidth="3" strokeLinejoin="round" strokeLinecap="round" /></svg></div>
            <div className="result-actions"><label className="field compact"><span>Review state</span><select value={selected.review_state} onChange={event => void updateReview(event.target.value as RunRecord['review_state'])}><option value="draft">Draft</option><option value="reviewed">Reviewed</option><option value="superseded">Superseded</option></select></label><button className="secondary" onClick={() => setScreen('scenarios')}>Explore scenarios →</button><button className="secondary" onClick={() => setScreen('paper')}>Paper rebalance →</button></div>
            {selected.config.strategy.name === 'allocation' && <div className="walk-forward"><div className="card-header"><div><p className="eyebrow">04 / VALIDATION</p><h3>Out of sample study</h3></div></div><p className="helper">Choose training and test windows in trading bars. The study selects a sleeve on training history, then scores it on later unseen bars.</p><div className="action-row"><Numeric label="Training bars" value={trainSize} min={20} onChange={setTrainSize} /><Numeric label="Test bars" value={testSize} min={5} onChange={setTestSize} /><button className="secondary" disabled={busy} onClick={() => void studyOutOfSample()}>Run study</button></div>{walkForward && <><div className="summary-grid walk-summary">{Object.entries(walkForward.summary).map(([key, value]) => <div className="summary-tile" key={key}><small>{metricLabel(key)}</small><strong>{typeof value === 'number' ? Number(value).toFixed(2) : String(value)}</strong></div>)}</div><div className="table-scroll"><table><thead><tr><th>Chosen sleeve</th><th>Train return</th><th>Test return</th><th>Train through</th><th>Test begins</th></tr></thead><tbody>{walkForward.folds.map((fold, index) => <tr key={index}><td>{fold.selected}</td><td>{percent(fold.train_return)}</td><td>{percent(fold.test_return)}</td><td>{fold.train_end}</td><td>{fold.test_begin}</td></tr>)}</tbody></table></div></>}</div>}
          </> : <p className="empty">Select a run to see performance, drawdown, and its allocation workflow.</p>}</section>
      </>}

      {screen === 'scenarios' && <>
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

      {screen === 'paper' && <><RunPicker runs={runs} selected={selected} onSelect={setSelected} /><section className="card"><div className="card-header"><div><p className="eyebrow">01 / PORTFOLIO</p><h2>Current paper holdings</h2></div><span className="soft-tag">Whole shares</span></div>
        {paperInput ? <><p className="helper">Target weights and latest prices come from your saved run. Enter shares and cash, or import a ticker,shares CSV.</p><label className="upload-field"><span>Import paper holdings CSV</span><input aria-label="Import paper holdings CSV" type="file" accept=".csv,text/csv" onChange={event => void importHoldings(event.target.files?.[0])} /><small>{holdingsFilename || 'ticker,shares columns · up to 1 MB'}</small></label><div className="table-scroll"><table><thead><tr><th>Asset</th><th>Target weight</th><th>Latest price</th><th>Current shares</th></tr></thead><tbody>{assets.map((row, index) => <tr key={index}><td><strong>{row.ticker}</strong></td><td>{percent(paperInput.target_weights[row.ticker] ?? 0)}</td><td>{money(paperInput.prices[row.ticker] ?? 0)}</td><td><input aria-label={`${row.ticker} current shares`} type="number" min="0" step="1" value={row.shares} onChange={event => updateAsset(index, { shares: Number(event.target.value) })} /></td></tr>)}</tbody></table></div><div className="paper-actions"><Numeric label="Available cash" value={cash} step={0.01} onChange={value => { setCash(value); setPaperResult(null) }} /><button className="primary" disabled={busy} onClick={() => void calculatePaper()}>Calculate paper rebalance</button></div></> : <p className="empty">Select a saved allocation run to populate target weights and prices.</p>}
      </section>{paperResult && <section className="card"><div className="card-header"><div><p className="eyebrow">02 / RECOMMENDATION</p><h2>Review share changes</h2></div><span className="soft-tag">Paper only</span></div><div className="summary-grid"><div className="summary-tile"><small>Starting value</small><strong>{money(paperResult.starting_value)}</strong></div><div className="summary-tile"><small>Leftover cash</small><strong>{money(paperResult.ending_cash)}</strong></div><div className="summary-tile"><small>Estimated cost</small><strong>{money(paperResult.estimated_cost)}</strong></div></div><div className="table-scroll"><table><thead><tr><th>Asset</th><th>Current</th><th>Target</th><th>Paper change</th><th>Estimated cost</th></tr></thead><tbody>{paperResult.trades.map(trade => <tr key={trade.ticker}><td>{trade.ticker}</td><td>{trade.current_shares}</td><td>{trade.target_shares}</td><td><span className={trade.delta_shares > 0 ? 'buy' : trade.delta_shares < 0 ? 'sell' : ''}>{trade.delta_shares > 0 ? `+${trade.delta_shares}` : trade.delta_shares}</span></td><td>{money(trade.estimated_cost)}</td></tr>)}</tbody></table></div><button className="primary" disabled={busy} onClick={() => void downloadPaper()}>Download paper packet CSV ↓</button><p className="helper">This is a simulation for review; no order is sent.</p></section>}</>}
    </main>
  </div>
}

function RunPicker({ runs, selected, onSelect }: {
  runs: RunRecord[]; selected: RunRecord | null; onSelect: (run: RunRecord | null) => void
}) {
  return <section className="card picker"><label className="field"><span>Use a saved backtest</span><select value={selected?.run_id ?? ''} onChange={event => onSelect(runs.find(run => run.run_id === event.target.value) ?? null)}><option value="">Choose a run</option>{runs.map(run => <option value={run.run_id} key={run.run_id}>{run.config.strategy?.name} · {run.config.start} · {run.run_id.slice(0, 8)}</option>)}</select></label><small>Run a strategy in Backtests first to populate its holdings and prices.</small></section>
}
