<!-- Copyright (c) 2026 Zenable, Inc. -->
# Expense submission

Budget owners require tenant isolation and a traceable debit. A valid payment changes the balance and audit history together; a refusal changes neither. Importers and interactive callers have the same obligation.

Finance changes reimbursement algorithms independently of submission integrity. A policy receives only an expense and returns payable cents or a refusal. It cannot access account state. A positive result never exceeds the original request.

Request identifiers are unique within a tenant. The same actor and payload may retry across entrypoints without paying twice or recalculating reimbursement. A changed actor or payload conflicts before policy or account lookup. Permissions can change between calls, so authorisation still precedes replay.

Accounts with the same identifier may exist in different tenants. A bare account identifier is insufficient to find mutable state.

This fixture has one process and no external effects. A production transaction must preserve the same guarantees across workers and crashes. Diagnostic snapshots belong to the test harness.
