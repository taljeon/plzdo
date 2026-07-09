# Basic Project Checks

Run:

```bash
./scripts/verify
```

The check is intentionally small:

- required docs exist;
- the root release gate scans this example for obvious private paths and secret markers before publishing;
- no live API is required.
