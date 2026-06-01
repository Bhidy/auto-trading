"""T2 research lane (OFFLINE only).

Modules here may import the heavy scientific stack (numpy/pandas/scipy/sklearn/
statsmodels from requirements-research.txt). They are run by the manual
`research.yml` workflow (workflow_dispatch) and emit STATIC ARTIFACTS into data/
that the pure-Python trading path reads. NOTHING in the trading/EOD path may
import this package — that would break the requests-only cloud invariant.
"""
