# Google connection check fix

The user approved fixing the reviewed Google connection-check defect, merging after review,
and deploying the Google relay to the existing AWS server. Existing demo deployments may be
cleared during the rollout.

Keep the proxy and relay architecture. Change only the deploy-time Google check: reject a
forwarded Google 401 with reconnect guidance, and reject other failed HTTP responses with
the provider's status and message. Successful checks still allow deployment. Regression tests
exercise the Medium adapter and prove that rejected checks create no n8n resources.

After local verification and independent review, merge a PR based on the latest remote branch.
Deploy that reviewed commit with `RELAY_BASE_URL=http://demo:8000`. Use the application's cleanup
path for any existing deployments; retain users and their connector credentials. Verify service
health, relay reachability from n8n, public relay isolation and Google proxy access without
sending Slack messages. Keep the local CI commit and untracked files intact.
