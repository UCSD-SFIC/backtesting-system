"""Canonical financial metrics and the XBRL concepts each one is read from.

This is the single mapping from SEC XBRL tags to the names the rest of the
terminal uses. Companies tag the same line item differently (and change tags
over time), so every metric lists concepts in priority order; for each period
the first concept with a value wins, and the API reports which one was used.

Only reported values live here. Ratios and derived measures (gross margin,
FCF, EBITDA, EV) belong to the analysis layer and should be built on top of
these inputs. To add or correct a metric, edit `METRICS`; stored facts are
re-normalized automatically because `definitions_hash()` changes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal

Statement = Literal["income", "balance", "cash_flow"]
Kind = Literal["flow", "instant"]

# Bump when normalization logic changes in a way that alters stored facts.
NORMALIZER_VERSION = 1


@dataclass(frozen=True)
class MetricDefinition:
    key: str
    label: str
    statement: Statement
    # "flow" covers a period (revenue); "instant" is a balance on a date (cash).
    kind: Kind
    unit: str
    concepts: tuple[str, ...]
    # Additive flows can be differenced (Q4 = FY - 9M). Per-share figures and
    # weighted share counts cannot, so their Q4 is left empty unless reported.
    additive: bool = True
    taxonomy: str = "us-gaap"

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "label": self.label,
            "statement": self.statement,
            "kind": self.kind,
            "unit": self.unit,
            "additive": self.additive,
            "concepts": [f"{self.taxonomy}:{concept}" for concept in self.concepts],
        }


def _flow(key: str, label: str, statement: Statement, *concepts: str) -> MetricDefinition:
    return MetricDefinition(key, label, statement, "flow", "USD", concepts)


def _instant(key: str, label: str, *concepts: str) -> MetricDefinition:
    return MetricDefinition(key, label, "balance", "instant", "USD", concepts)


METRICS: tuple[MetricDefinition, ...] = (
    # Income statement
    _flow(
        "revenue", "Revenue", "income",
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueGoodsNet",
        "RevenuesNetOfInterestExpense",
    ),
    _flow(
        "cost_of_revenue", "Cost of revenue", "income",
        "CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold",
    ),
    _flow("gross_profit", "Gross profit", "income", "GrossProfit"),
    _flow(
        "research_and_development", "Research and development", "income",
        "ResearchAndDevelopmentExpense",
    ),
    _flow(
        "selling_general_admin", "Selling, general and administrative", "income",
        "SellingGeneralAndAdministrativeExpense",
    ),
    _flow("operating_income", "Operating income", "income", "OperatingIncomeLoss"),
    _flow(
        "interest_expense", "Interest expense", "income",
        "InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt",
    ),
    _flow(
        "pretax_income", "Income before income taxes", "income",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    ),
    _flow("income_tax", "Income tax expense", "income", "IncomeTaxExpenseBenefit"),
    _flow(
        "net_income", "Net income", "income",
        "NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic",
    ),
    MetricDefinition(
        "eps_basic", "EPS (basic)", "income", "flow", "USD/shares",
        ("EarningsPerShareBasic",), additive=False,
    ),
    MetricDefinition(
        "eps_diluted", "EPS (diluted)", "income", "flow", "USD/shares",
        ("EarningsPerShareDiluted",), additive=False,
    ),
    MetricDefinition(
        "shares_basic", "Weighted average shares (basic)", "income", "flow", "shares",
        ("WeightedAverageNumberOfSharesOutstandingBasic",), additive=False,
    ),
    MetricDefinition(
        "shares_diluted", "Weighted average shares (diluted)", "income", "flow", "shares",
        ("WeightedAverageNumberOfDilutedSharesOutstanding",), additive=False,
    ),
    # Balance sheet
    _instant(
        "cash_and_equivalents", "Cash and cash equivalents",
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ),
    _instant(
        "short_term_investments", "Short-term investments",
        "ShortTermInvestments",
        "MarketableSecuritiesCurrent",
        "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
    ),
    _instant("accounts_receivable", "Accounts receivable", "AccountsReceivableNetCurrent"),
    _instant("inventory", "Inventory", "InventoryNet"),
    _instant("total_current_assets", "Total current assets", "AssetsCurrent"),
    _instant("total_assets", "Total assets", "Assets"),
    _instant("total_current_liabilities", "Total current liabilities", "LiabilitiesCurrent"),
    _instant(
        "short_term_debt", "Short-term debt and current portion of long-term debt",
        "DebtCurrent",
        "LongTermDebtCurrent",
        "LongTermDebtAndCapitalLeaseObligationsCurrent",
        "ShortTermBorrowings",
    ),
    _instant(
        "long_term_debt", "Long-term debt (non-current)",
        "LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations",
    ),
    _instant("total_liabilities", "Total liabilities", "Liabilities"),
    _instant(
        "retained_earnings", "Retained earnings", "RetainedEarningsAccumulatedDeficit"
    ),
    _instant(
        "total_equity", "Total shareholders' equity",
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
    # Cash flow statement
    _flow(
        "operating_cash_flow", "Cash from operations", "cash_flow",
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ),
    _flow(
        "depreciation_amortization", "Depreciation and amortization", "cash_flow",
        "DepreciationDepletionAndAmortization",
        "DepreciationAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
    ),
    _flow(
        "stock_based_compensation", "Stock-based compensation", "cash_flow",
        "ShareBasedCompensation",
    ),
    _flow(
        "capital_expenditures", "Capital expenditures", "cash_flow",
        "PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
    ),
    _flow(
        "investing_cash_flow", "Cash from investing", "cash_flow",
        "NetCashProvidedByUsedInInvestingActivities",
    ),
    _flow(
        "dividends_paid", "Dividends paid", "cash_flow",
        "PaymentsOfDividends", "PaymentsOfDividendsCommonStock",
    ),
    _flow(
        "share_repurchases", "Share repurchases", "cash_flow",
        "PaymentsForRepurchaseOfCommonStock",
    ),
    _flow(
        "financing_cash_flow", "Cash from financing", "cash_flow",
        "NetCashProvidedByUsedInFinancingActivities",
    ),
)

METRICS_BY_KEY: dict[str, MetricDefinition] = {metric.key: metric for metric in METRICS}
STATEMENTS: tuple[Statement, ...] = ("income", "balance", "cash_flow")

# Point-in-time share counts used for market cap, newest value wins.
# (taxonomy, concept) in priority order.
SHARES_OUTSTANDING_CONCEPTS: tuple[tuple[str, str], ...] = (
    ("dei", "EntityCommonStockSharesOutstanding"),
    ("us-gaap", "CommonStockSharesOutstanding"),
)


def metrics_for(statement: Statement) -> list[MetricDefinition]:
    return [metric for metric in METRICS if metric.statement == statement]


def definitions_hash(metrics: tuple[MetricDefinition, ...] = METRICS) -> str:
    """Fingerprint of the mapping; stored facts are rebuilt when it changes."""
    payload = json.dumps(
        {"version": NORMALIZER_VERSION, "metrics": [metric.to_dict() for metric in metrics]},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]
