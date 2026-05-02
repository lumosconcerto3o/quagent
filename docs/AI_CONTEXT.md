# QuAgent AI Context

Project root:

D:\quagent

Repository:

https://github.com/lumosconcerto3o/quagent

Stable checkpoints:

- v0.1-readonly-stable
- v0.2-real-data-dry-run

Current phase:

Real-data dry-run pipeline is implemented and verified.

Next phase:

Audit and stabilize dry-run semantics before any paper order execution.

Verified state:

- GitHub private repo exists.
- TWS paper read-only connection works.
- connectAsync uses readonly=True.
- TWS Read-Only API remains enabled.
- Account summary reads correctly.
- SPY delayed quote works with quote_quality=complete.
- scripts/real_data_dry_run.py exists and has been run successfully.
- tests/test_real_data_dry_run.py exists.
- pytest -v: 112 passed.
- IBKRClient.submit_order() and cancel_order() remain disabled.
- ExecutionEngine dry_run=True by default.
- broker_order_id remains None in dry-run.
- No ib.placeOrder or ib.cancelOrder implementation is allowed.

Current repo workflow:

- main branch should stay stable.
- Use feature branches for experimental Copilot/Claude changes.
- Run pytest before every commit.
- Push only tested checkpoints.

Do not implement paper submit or live trading until explicitly approved.
