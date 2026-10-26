# Verification results

Date: 25 October 2026.

## Automated tests

```text
pytest -q
106 passed in 9.21s
```

The suite includes the original corrected workflow and new coverage for:

- Direct records URLs blocked even with a faculty login until webcam step-up succeeds.
- Same-account registered-face matching; rejection of another registered faculty member or an unknown/unusable face.
- Missing-model, malformed-image, missing/non-ASCII CSRF, inactive account, and missing enrollment failures.
- Verification expiry, date-filter protection, manual locking/logout, account binding, and enrollment change/deactivation revocation.
- Faculty-only class scoping and review POST protection, not just client-side visibility.
- Automatic Present/auto-approved status and explicit review-success API fields.
- No fabricated faculty reviewer for automatic actions; timestamp plus audit insertion.
- Duplicate/concurrent scan protection and rejection history that cannot be undone by rescanning.
- Optional legacy pending mode and genuine manual faculty confirmation.
- Migration backup, row/ID/status preservation, custom indexes/triggers and FK-child preservation, rollback on copy failure, repeatability, and fresh initialization.

Temporary SQLite databases, a controlled campus clock, and synthetic 512-element embeddings are used. Inference is stubbed when necessary; matching, guards, CSRF, transactions, schema constraints, and SQL writes are real.

## Chromium browser checks

An isolated synthetic test server and canvas-backed simulated camera were used. Verified:

1. Faculty login, selected-class camera, continuous student recognition, and visible Present / Review successful (automatic).
2. Repeated frames produce only one student attendance entry.
3. Records link opens the webcam verification page, with no student table visible before success.
4. Another registered faculty face receives 403 and does not unlock the signed-in faculty account.
5. Correct faculty verification opens own-class records; another faculty's seeded student is absent.
6. Lock records -> direct URL is blocked and returns to verification.
7. Server-side verification expiry returns verified=false and refuses a records reload.
8. Client expiry hides the table and navigates to verification (tested with a shortened simulated status response).

The synthetic test server was stopped afterward. Its inference shim and control files are not included in the downloadable application.

## Environment and limits

Core test environment: Python 3.13.16, Flask 3.1.3, NumPy/OpenCV preinstalled in the sandbox, pytest. InsightFace and ONNX Runtime were not installed here. The recommended full-model Python 3.10/3.11 environment and real model/device access still require validation.

No real hardware webcam, real faculty/student face, real model inference, biometric accuracy, liveness/anti-spoofing, or production load/deployment was verified. The production code contains no fake-recognition fallback. Automatic approval is an explicit requested policy, not a guarantee that a biometric match is correct.
