# Findings Ledger

This ledger records product-level limitations that remain relevant after release. Runtime finding records use the versioned local JSON contract.

| ID | Status | Scope | Evidence | Reopen trigger |
| --- | --- | --- | --- | --- |
| LOCAL-1 | accepted-risk | Local-only behavior is not an OS firewall guarantee. | Source and behavior gates contain no transport in the default runtime. | A bundled default command gains network or provider access. |
| P5-1 | accepted-risk | P5 protects a bounded local write but cannot prove semantic correctness. | Plans bind bytes, target identity, confirmation, verification, and rollback. | An apply path accepts arbitrary commands or bypasses a required binding. |
| REVIEW-1 | accepted-risk | Manual movement of a review bundle can create external egress outside PlzDo Local. | The runtime exposes prepare, validate, and import only. | A provider adapter or send command is added. |
| HOST-1 | accepted-risk | A privileged local process can inspect local state. | State roots and permissions are visible to the operator. | PlzDo claims process isolation or encrypted storage. |

Removing a limitation from this table requires evidence that its reopen condition can no longer occur. Baseline movement alone is not closure.
