# Google Connection Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Reject unsuccessful Google checks before creating n8n resources and deploy the reviewed fix.

**Architecture:** Keep GoogleApi.call forwarding provider responses. check_connection explicitly rejects 401 with GoogleConnectionExpired and other HTTP errors with GoogleError. Reuse the Medium adapter's existing failure cleanup and the AWS deployment scripts.

**Tech Stack:** Python, pytest, respx, FastAPI, n8n, Docker Compose, AWS EC2.

### Task 1: Regressions and fix

Files: `app/backend/tests/test_n8n_adapter.py`, `app/backend/workflow_demo/google.py`.

- [ ] Run the baseline backend suite: `python -m pytest -q` (190 pass).
- [ ] Add a parameterized Medium deployment regression for forwarded Google HTTP 401, 403 and 503. Mock credential/workflow endpoints, require AdapterError with reconnect guidance for 401 and provider status/message otherwise, and assert none of those n8n endpoints were called.
- [ ] Run the regression alone and observe failures because deployment continues.
- [ ] Replace check_connection's ignored response with:

```python
resp = api.call("GET", "oauth2/v3/userinfo", base_url=GOOGLEAPIS)
if resp.status_code == 401:
    raise GoogleConnectionExpired()
if resp.status_code >= 400:
    raise GoogleError(f"Google connection check error {resp.status_code}: {_message(resp)}")
```

- [ ] Run the focused regression, full backend tests, Ruff lint/format, and catalog checks.
- [ ] Update `docs/progress.md`, commit, obtain independent review, address any material findings, then push the fast-forward commit to `claude/amazing-maxwell-6md3og` and create/merge its PR after CI passes.

### Task 2: AWS rollout

- [ ] Inventory current deployments with `/api/admin/overview`. Stop any remaining deployment through `/api/admin/users/{username}/deployments/{workflow_id}/stop`; wait for cleanup and run `/api/admin/sweep`.
- [ ] Copy the existing ignored production/infrastructure/bot settings into the reviewed checkout, append `RELAY_BASE_URL=http://demo:8000`, and run `deploy/aws/deploy.sh` with the existing SSH key.
- [ ] Verify EC2/container health, deployed source hashes, `/api/health`, authenticated `/api/admin/setup`, internal relay's expected 401 response from n8n, and public relay's 404 response. Check Google APIs through Nango using the owner's existing connection without sending messages.
- [ ] Record rollout evidence in `docs/progress.md`, sync the original workspace while preserving its local changes, and report the merged PR and any live limitations.
