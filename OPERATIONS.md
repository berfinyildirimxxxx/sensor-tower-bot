# Operations Guide

## Schedule

The Daily Alert workflow runs every day at 17:00 Istanbul time (`0 14 * * *` in UTC).

## Manual Run

1. Open the repository on GitHub.
2. Go to the **Actions** tab.
3. Click the **Daily Alert** workflow.
4. Click **Run workflow**.

## Test Mode

When starting a manual run, set `test_mode=true` to run `python main.py --test`. This sends the Slack test message instead of running the full Sensor Tower pipeline.

## View Logs

1. Open the **Actions** tab.
2. Click any **Daily Alert** run.
3. Open the job steps to inspect logs and failures.

## Update Secrets

1. Open the repository on GitHub.
2. Go to **Settings**.
3. Open **Secrets and variables → Actions**.
4. Update:
   - `SENSOR_TOWER_API_KEY`
   - `SLACK_WEBHOOK_URL`

## Disable Temporarily

1. Open the **Actions** tab.
2. Click the **Daily Alert** workflow.
3. Open the **...** menu.
4. Click **Disable workflow**.

## Cost Note

GitHub Actions free tier is more than enough for a once-per-day Python workflow like this.
