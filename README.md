# Konflux Retest Metrics Analyzer

Automated analysis of retest/rerun metrics for Konflux CI/CD pipelines across GitHub and GitLab repositories.

## Overview

This tool analyzes historical CI/CD data to detect flaky tests by counting how many times commits are retested without code changes. It runs hourly via GitHub Actions and pushes metrics to Grafana Cloud for visualization.

## Features

- ✅ **Multi-platform** - Analyzes both GitHub and GitLab repositories
- ✅ **Grafana Cloud integration** - Real-time metrics visualization
- ✅ **Automated analysis** - Runs hourly via GitHub Actions
- ✅ **Historical tracking** - Stores JSON results in the repo
- ✅ **Per-PR metrics** - Track individual PRs/MRs over time

## How It Works

### Retest Detection

The tool distinguishes between two scenarios:

**Retest (Flaky Test)**
- Same commit SHA tested multiple times
- Triggered by `/retest`, "Re-run" button, or CI retry
- Indicates flaky test or infrastructure issue
- **Counted as a retest**

**New Commit (Code Change)**
- New commit SHA pushed to PR/MR
- Developer fixes failing test with new code
- Normal development flow
- **Not counted as a retest**

### GitHub Detection

Uses GitHub's Check Suites API to count instances:

```python
# When someone clicks "Re-run", GitHub creates a NEW check suite instance
suite_count = count_check_suites(commit_sha)
retests = suite_count - 1  # Subtract original run
```

### GitLab Detection

Counts multiple pipelines for the same commit SHA:

```python
# Get all pipelines for a commit
pipelines = get_commit_pipelines(sha)
# Filter to merge_request_event only
mr_pipelines = [p for p in pipelines if p['source'] == 'merge_request_event']
retests = len(mr_pipelines) - 1
```

## Metrics Collected

### Per-PR/MR Metrics
- `github_pr_retests{repository, pr_number, author}` - Retests for individual GitHub PR
- `gitlab_mr_retests{project, mr_number, author}` - Retests for individual GitLab MR

### Aggregated Metrics
- `*_retests_total{repository/project}` - Total retests per repo/project
- `*_retest_rate_percent{repository/project}` - Percentage of PRs/MRs with retests
- `*_avg_retests_per_pr{repository/project}` - Average retests per PR/MR

## Dashboard

The Grafana dashboard shows:
- **Retests per PR/MR Over Time** - Individual data points for each merged PR/MR (7-day view)
- **Retest Rate Trends** - Percentage of PRs/MRs requiring retests (0-500% scale)
- **Average Retests per PR/MR** - Average retests across repositories/projects (0-5 scale)

Filters available by platform (GitHub/GitLab) and repository/project.

## Repositories Analyzed

### GitHub (11 repositories)
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

### GitLab (7 projects)
- insights-qe/iqe-ccx-plugin
- ccx/ccx-data-pipeline
- ccx/content-service
- ccx/ccx-load-test
- ccx/parquet-factory
- ccx/ccx-upgrades-data-eng
- ccx/ccx-upgrades-inference

### JSON Output

Results are stored in the repository:
- `github_flakiness_7days.json` - GitHub analysis results
- `gitlab_flakiness_7days.json` - GitLab analysis results

Updated hourly with the latest 7-day window of data.

## Troubleshooting

### No Retests Found

If analysis shows 0 retests but you know there were reruns:

1. Check Konflux pipeline detection - Pipelines must be named "on-pull-request"
2. Verify date range - Reruns might be outside the 7-day window
3. Check you're viewing merged PRs/MRs - Open ones are not analyzed

### Rate Limits

- **GitHub**: 5000 requests/hour with authentication (automatically handled)
- **GitLab**: Varies by instance (token is configured)

The tool handles rate limits automatically with retries and delays.

## License

MIT
