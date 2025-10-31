# Grafana Cloud Deployment Setup

This guide explains how to deploy the Konflux metrics tracking system to Grafana Cloud using GitHub Actions.

## Overview

The system runs hourly via GitHub Actions and pushes metrics to Grafana Cloud. It analyzes both GitHub and GitLab repositories for retest/rerun patterns in Konflux CI/CD pipelines.

## Grafana Cloud Credentials

Your Grafana Cloud instance: **lsolarov.grafana.net**

Prometheus Push Endpoint:
- **URL**: `https://prometheus-prod-65-prod-eu-west-2.grafana.net/api/prom/push`
- **User ID**: `2770427`
- **API Token**: Stored in `/Users/lsolarov/Documents/SECURITY/grafana_cloud_token`

## GitHub Repository Secrets Setup

To enable the GitHub Actions workflow to push metrics to Grafana Cloud, you need to add the following secrets to your GitHub repository.

### Adding Secrets

1. Go to your GitHub repository: https://github.com/lenasolarova/konflux_metrics
2. Navigate to **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret**
4. Add each of the following secrets:

### Required Secrets

#### 1. GRAFANA_CLOUD_URL
- **Name**: `GRAFANA_CLOUD_URL`
- **Value**: `https://prometheus-prod-65-prod-eu-west-2.grafana.net/api/prom/push`

#### 2. GRAFANA_CLOUD_USER
- **Name**: `GRAFANA_CLOUD_USER`
- **Value**: `2770427`

#### 3. GRAFANA_CLOUD_TOKEN
- **Name**: `GRAFANA_CLOUD_TOKEN`
- **Value**: Get from your token file with this command:
  ```bash
  cat /Users/lsolarov/Documents/SECURITY/grafana_cloud_token
  ```
  Copy the entire token (starts with `glc_...`)

#### 4. GITLAB_TOKEN (if not already set)
- **Name**: `GITLAB_TOKEN`
- **Value**: Get from your GitLab token file:
  ```bash
  cat /Users/lsolarov/Downloads/GL\ token.txt
  ```

Note: `GITHUB_TOKEN` is automatically provided by GitHub Actions, no need to add it manually.

## Workflow Behavior

Once secrets are configured:
- **Schedule**: Runs every hour (`0 * * * *`)
- **Manual trigger**: Available via GitHub Actions UI
- **Analysis window**: Last 7 days of merged PRs/MRs
- **Metrics destination**: Grafana Cloud (no local Pushgateway needed)

### Repositories Analyzed

**GitHub** (11 repos):
- RedHatInsights/insights-ccx-messaging
- RedHatInsights/insights-results-aggregator
- RedHatInsights/insights-results-aggregator-exporter
- RedHatInsights/insights-content-template-renderer
- RedHatInsights/insights-behavioral-spec
- RedHatInsights/insights-results-aggregator-cleaner
- RedHatInsights/insights-operator-gathering-conditions-service
- RedHatInsights/ccx-notification-service
- RedHatInsights/ccx-notification-writer
- RedHatInsights/obsint-mocks
- RedHatInsights/insights-results-smart-proxy

**GitLab** (7 projects):
- insights-qe/iqe-ccx-plugin
- ccx/ccx-data-pipeline
- ccx/content-service
- ccx/ccx-load-test
- ccx/parquet-factory
- ccx/ccx-upgrades-data-eng
- ccx/ccx-upgrades-inference

## Metrics Collected

### Per-PR/MR Metrics
- `github_pr_retests{repository, pr_number, author}` - Number of retests for individual GitHub PR
- `gitlab_mr_retests{project, mr_number, author}` - Number of retests for individual GitLab MR

### Aggregated Metrics
- `github_flakiness_retests_total{repository}` - Total retests per repository
- `github_flakiness_retest_rate_percent{repository}` - Percentage of PRs with retests
- `github_flakiness_avg_retests_per_pr{repository}` - Average retests per PR
- `gitlab_flakiness_retests_total{project}` - Total retests per project
- `gitlab_flakiness_retest_rate_percent{project}` - Percentage of MRs with retests
- `gitlab_flakiness_avg_retests_per_mr{project}` - Average retests per MR

## Dashboard Import

After the workflow runs successfully and pushes metrics to Grafana Cloud:

1. Log in to Grafana Cloud: https://lsolarov.grafana.net
2. Go to **Dashboards** → **Import**
3. Upload the dashboard JSON: `grafana-dashboard-v2.json`
4. Select your Grafana Cloud Prometheus data source
5. Click **Import**

The dashboard includes:
- **Retests per PR/MR Over Time**: Individual data points for each merged PR/MR (7-day view)
- **Retest Rate Trends**: Percentage of PRs/MRs requiring retests (0-500% scale)
- **Average Retests per PR/MR**: Average retests across repositories/projects (0-5 scale)

### Making Dashboard Public

To share the dashboard publicly:
1. Open your dashboard in Grafana Cloud
2. Click **Share** (share icon in top bar)
3. Enable **Public dashboard**
4. Copy the public URL
5. Share with your team!

## Testing the Setup

### Manual Workflow Run

Test the workflow before waiting for the hourly schedule:

1. Go to your repo: https://github.com/lenasolarova/konflux_metrics
2. Navigate to **Actions** tab
3. Select **Hourly Retest Metrics Analysis** workflow
4. Click **Run workflow** → **Run workflow**
5. Monitor the run to ensure metrics are pushed successfully

### Verify Metrics in Grafana Cloud

1. Log in to Grafana Cloud: https://lsolarov.grafana.net
2. Go to **Explore**
3. Select your Prometheus data source
4. Query for metrics:
   ```promql
   github_pr_retests
   ```
   or
   ```promql
   gitlab_mr_retests
   ```
5. You should see data points for analyzed PRs/MRs

## Local Testing

To test locally before deploying to GitHub Actions:

```bash
cd "/Users/lsolarov/Documents/KONFLUX RETEST METRIC/local"

# Set environment variables
export GITHUB_TOKEN=$(cat /Users/lsolarov/Documents/SECURITY/github_access_token)
export GITLAB_TOKEN=$(cat /Users/lsolarov/Downloads/GL\ token.txt)
export GRAFANA_CLOUD_URL="https://prometheus-prod-65-prod-eu-west-2.grafana.net/api/prom/push"
export GRAFANA_CLOUD_USER="2770427"
export GRAFANA_CLOUD_TOKEN=$(cat /Users/lsolarov/Documents/SECURITY/grafana_cloud_token)

# Run analyzers
python3 analyze_github_flakiness.py  # GitHub
python3 analyze_gitlab_flakiness.py      # GitLab
```

## Troubleshooting

### Workflow fails with authentication error
- Verify all secrets are correctly set in GitHub repository settings
- Check that the Grafana Cloud token hasn't expired
- Ensure token has proper permissions

### No data appears in Grafana
- Check workflow logs for push errors
- Verify Prometheus data source is configured in Grafana Cloud
- Check time range in dashboard (set to "Last 7 days")
- Ensure metrics are being pushed (check workflow logs for "✅ Metrics successfully pushed")

### Rate limit errors
- GitHub: Ensure `GITHUB_TOKEN` secret is set (should be automatic)
- GitLab: Verify `GITLAB_TOKEN` is valid and has `read_api` scope

## Next Steps

1. Add all required secrets to GitHub repository
2. Manually trigger workflow to test
3. Import dashboard to Grafana Cloud
4. Make dashboard public and share URL
5. Monitor hourly runs for issues

## Support

For issues or questions:
- GitHub Issues: https://github.com/lenasolarova/konflux_metrics/issues
- Check workflow logs: https://github.com/lenasolarova/konflux_metrics/actions
