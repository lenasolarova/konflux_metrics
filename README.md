# Konflux Retest Metrics Analyzer

Automated analysis of retest/rerun metrics for Konflux CI/CD pipelines across GitHub and GitLab repositories.

## Overview

This tool analyzes CI/CD data to detect flaky tests by counting how many times commits are retested. It runs twice daily and displays metrics in a Grafana dashboard.

## Features

- ✅ **Multi-platform** - Analyzes both GitHub and GitLab repositories
- ✅ **Grafana dashboard** - Visual representation of retest metrics over time
- ✅ **Automated analysis** - Runs twice daily (9 AM and 9 PM UTC) via GitHub Actions and GitLab CI
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

The Grafana dashboard ([grafana-dashboard-unwrapped.json](grafana-dashboard-unwrapped.json)) displays:
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
- `github_flakiness_current.json` - GitHub PR metrics (last 24 hours)
- `gitlab_flakiness_current.json` - GitLab MR metrics (last 24 hours)
- `github_flakiness_historical.json` - GitHub PR metrics (last 90 days)
- `gitlab_flakiness_historical.json` - GitLab MR metrics (last 90 days) 

These files are updated twice daily (9 AM and 9 PM UTC) and committed to the repository.

## Setup

### GitHub Actions
The workflow (`.github/workflows/retest-metrics.yaml`) runs automatically on schedule and can be triggered manually via workflow_dispatch.

The workflow (`.github/workflows/append-historical.yaml`) runs automatically on schedule (one hour behind the other data collection pipelines) and wrangles the data in the historical files (appending new data and trimming data older than 90 days).

### GitLab CI
The pipeline (`.gitlab-ci.yml`) runs on schedule (configured in GitLab settings) and pushes results to the GitHub repository.
