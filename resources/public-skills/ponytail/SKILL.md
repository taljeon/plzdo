---
name: ponytail
description: Prefer the smallest maintainable implementation that satisfies the verified requirement.
---

# Ponytail

Use this skill when a task is accumulating unnecessary machinery.

## Decision Rule

1. Confirm that the requested behavior is necessary.
2. Reuse the standard library and existing project patterns first.
3. Choose one direct implementation before introducing a framework or abstraction.
4. Add configuration only for a current, demonstrated variation.
5. Match test depth to behavioral risk and stop when the requirement is proven.

Minimality does not relax data safety, correctness, accessibility, or required evidence.
