# Konflux Retest Metrics Analyzer

Automated analysis of retest/rerun metrics for Konflux CI/CD pipelines across GitHub and GitLab repositories.

## Overview

This tool analyzes CI/CD data to detect flaky tests by counting how many times commits are retested. It runs twice a day and displays metrics in a Grafana dashboard. 

The main tooling lives in [GitHub](https://github.com/RedHatInsights/konflux_metrics) where the JSON files are updated, appended and read by Grafana (via Infinity). 

Data also comes from GitLab (necessary for our GitLab repositories behind VPN) twice a day.

All of this is automated and needs no manual inetrvention at any point.

## Features

- ✅ **Multi-platform** - Analyzes both GitHub and GitLab repositories
- ✅ **Grafana dashboard** - Visual representation of retest metrics over time (up to 90 days)
- ✅ **Automated analysis** - Runs twice a day (9 AM and 9 PM UTC) via GitHub Actions and GitLab CI
- ✅ **Per-PR metrics** - Track individual PRs/MRs over time
- ✅ **Clickable links** - Click on data points to open the PR/MR

## How It Works

### Retest Detection

Detection is done using the number of `/retest` comments (and also Branch updates for GitHub repositories) because we do not have an API from Konflux that would be capable of providing the data directly. While not perfect accuracy-wise, it is the only realistic option without a Konflux API.

## Metrics Collected

- Total retests per PR/MR
- Total commits per PR/MR
- Retest rate (percentage of PRs/MRs with retests)
- Average retests per PR/MR and per commit

## Dashboard

The [Grafana dashboard](https://grafana.app-sre.devshift.net/d/cf3bjtzod9blsa/konflux-retest-metrics?orgId=1) deployes in app-sre grafana displays:
- **Retests per merged PR/MR** - Time series graph with individual data points (history goes back 90 days)
  - Purple dots for GitHub PRs
  - Orange dots for GitLab MRs
  - Clickable to open the specific PR/MR

- **GitHub Pull Requests** - Table view of recent GitHub PRs
- **GitLab Merge Requests** - Table view of recent GitLab MRs

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

## JSON Output

The analysis scripts generate JSON files that are consumed by the Grafana dashboard via the Infinity datasource:

These are used for ammending the historical files only:
- [`github_flakiness_current.json`](https://raw.githubusercontent.com/RedHatInsights/konflux_metrics/main/github_flakiness_current.json) - GitHub PR metrics (last 24 hours)
- [`gitlab_flakiness_current.json`](https://raw.githubusercontent.com/RedHatInsights/konflux_metrics/main/gitlab_flakiness_current.json) - GitLab MR metrics (last 24 hours)

These are used directly by Grafana:
- [`github_flakiness_historical.json`](https://raw.githubusercontent.com/RedHatInsights/konflux_metrics/main/github_flakiness_historical.json) - GitHub PR metrics (last 90 days)
- [`gitlab_flakiness_historical.json`](https://raw.githubusercontent.com/RedHatInsights/konflux_metrics/main/gitlab_flakiness_historical.json) - GitLab MR metrics (last 90 days) 

These files are updated twice daily (9 AM and 9 PM) and committed to the repository.

## Setup

### GitHub Actions
The workflow (`.github/workflows/retest-metrics.yaml`) runs automatically on schedule but can be triggered manually.

The workflow (`.github/workflows/append-historical.yaml`) runs automatically on schedule (one hour behind the other data collection pipelines) and wrangles the data in the historical files (appending new data and trimming data older than 90 days).

There is also another workflow (`.github/workflows/backfill-historical.yaml`) which can be run manually to backfill the history in case of a new project or data loss (by default set to 90 days).

### GitLab CI
The pipeline (`.gitlab-ci.yml`) runs on schedule and pushes results to the GitHub repository. 
It also has a manual job that can be run to backfill the 90 days in case of a new project or data loss.
