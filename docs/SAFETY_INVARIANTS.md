# QuAgent Safety Invariants

These rules must not be violated.

## Broker Safety

1. Do not implement ib.placeOrder().
2. Do not implement ib.cancelOrder().
3. Do not implement reqGlobalCancel().
4. IBKRClient.submit_order() must remain disabled until paper-order phase is explicitly approved.
5. IBKRClient.cancel_order() must remain disabled until paper-order phase is explicitly approved.
6. TWS Read-Only API must remain enabled during read-only and dry-run phases.

## Execution Safety

1. ExecutionEngine must default to dry_run=True.
2. dry_run=True must never call broker submit_order().
3. ExecutionEngine must require OMS status VALIDATED.
4. ExecutionEngine must respect kill switch state.
5. broker_order_id must remain None in dry-run mode.

## Risk Safety

1. RiskEngine must reject incomplete quote data.
2. RiskEngine must enforce max_order_notional_usd.
3. RiskEngine must reject unsupported asset classes.
4. RiskEngine must enforce require_stop_loss when configured.
5. RiskEngine must respect kill switch state.

## Live Trading

1. live.yaml must default to allow_live=false.
2. live trading must require manual confirmation.
3. no market orders in live mode.
4. no options, futures, forex, crypto in MVP live mode.
5. no live trading until paper validation is complete.

## Agent Safety

1. LLM/agent may only generate candidate signals.
2. Agent must not call IBKR directly.
3. Agent must not modify risk config.
4. Agent must not disable kill switch.
5. Signal must pass Schema -> RiskEngine -> OMS -> ExecutionEngine.
