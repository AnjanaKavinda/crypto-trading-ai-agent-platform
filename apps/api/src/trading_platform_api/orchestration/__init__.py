"""Bounded workflow orchestration for validated research outputs."""

from trading_platform_api.orchestration.spot_analysis_fanout import (
    SpotAnalysisFanoutAssessment,
    SpotAnalysisFanoutError,
    SpotAnalysisFanoutResult,
    SpotAnalysisTask,
    SpotAnalysisTaskOutcome,
    SpotAnalysisTaskReason,
    SpotAnalysisTaskStatus,
    SpotAnalysisUnavailable,
    run_spot_analysis_fanout,
    run_spot_analysis_fanout_with_independence,
)
from trading_platform_api.orchestration.spot_debate import (
    SpotDebateConclusion,
    SpotDebateError,
    SpotDebateResult,
    SpotThesisBranch,
    compose_spot_debate,
)
from trading_platform_api.orchestration.spot_market_thesis import (
    SpotMarketThesis,
    SpotMarketThesisError,
    SpotThesisCase,
    ThesisAssumptionState,
    ThesisCaseState,
    ThesisInvalidationCandidate,
    ThesisInvalidationState,
    compose_spot_market_thesis,
)
from trading_platform_api.orchestration.spot_results import (
    SpotResultState,
    build_spot_result_graph,
    run_spot_result_graph,
)
from trading_platform_api.orchestration.spot_rsi_finding import (
    SPOT_RSI_FINDING_METHOD,
    adapt_rsi14_finding,
)

__all__ = [
    "SpotAnalysisFanoutError",
    "SpotAnalysisFanoutAssessment",
    "SpotAnalysisFanoutResult",
    "SpotAnalysisTask",
    "SpotAnalysisTaskOutcome",
    "SpotAnalysisTaskReason",
    "SpotAnalysisTaskStatus",
    "SpotAnalysisUnavailable",
    "SPOT_RSI_FINDING_METHOD",
    "adapt_rsi14_finding",
    "SpotResultState",
    "build_spot_result_graph",
    "run_spot_analysis_fanout",
    "run_spot_analysis_fanout_with_independence",
    "run_spot_result_graph",
    "SpotDebateConclusion",
    "SpotDebateError",
    "SpotDebateResult",
    "SpotThesisBranch",
    "compose_spot_debate",
    "SpotMarketThesis",
    "SpotMarketThesisError",
    "SpotThesisCase",
    "ThesisAssumptionState",
    "ThesisCaseState",
    "ThesisInvalidationCandidate",
    "ThesisInvalidationState",
    "compose_spot_market_thesis",
]
