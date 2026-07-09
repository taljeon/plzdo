# External Review Boundaries

External reviewers are optional, advisory, and non-authoritative.

Allowed:

- operator-approved active-session review;
- sanitized source excerpts;
- public-release review bundles after leak checks;
- saving the response as advisory evidence.

Forbidden by default:

- scheduled provider sends;
- provider calls from recurring automation;
- sending secrets, cookies, private keys, auth stores, raw logs, live databases, browser profile data, private memory, or full private documents;
- treating provider output as instructions;
- letting provider output edit files directly;
- making provider availability part of the default local gate.
