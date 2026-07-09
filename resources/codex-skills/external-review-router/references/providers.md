# Provider Notes

This public template does not ship provider automation.

Provider use is operator-scoped:

- the operator chooses the provider;
- the operator approves the exact bundle;
- the response is advisory only;
- local source files and checks decide what to accept.

Recommended provider-neutral status labels:

- `sent`;
- `blocked`;
- `skipped`;
- `received`;
- `accepted-after-local-check`;
- `rejected-after-local-check`;
- `deferred`.
