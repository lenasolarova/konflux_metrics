#!/usr/bin/env python3
"""Push metrics directly to Grafana Cloud Prometheus endpoint"""

import json
import os
import sys
import time
import requests
from typing import Dict, List


def create_prometheus_metric(metric_name: str, labels: Dict[str, str], value: float, timestamp_ms: int) -> str:
    """Create a Prometheus metric in exposition format"""
    label_str = ','.join([f'{k}="{v}"' for k, v in labels.items()])
    return f"{metric_name}{{{label_str}}} {value} {timestamp_ms}\n"


def push_github_metrics(metrics_batch: List[str], timestamp_ms: int):
    """Read GitHub flakiness JSON and add metrics to batch"""
    with open('github_flakiness_7days.json', 'r') as f:
        data = json.load(f)

    # Process each repository
    for repo_name, repo_data in data.get('repositories', {}).items():
        summary = repo_data.get('summary', {})

        # Add aggregated metrics
        metrics_batch.append(create_prometheus_metric(
            'github_flakiness_prs_analyzed_total',
            {'repository': repo_name},
            summary.get('total_prs_analyzed', 0),
            timestamp_ms
        ))
        metrics_batch.append(create_prometheus_metric(
            'github_flakiness_retests_total',
            {'repository': repo_name},
            summary.get('total_retests', 0),
            timestamp_ms
        ))

        if summary.get('total_prs_analyzed', 0) > 0:
            metrics_batch.append(create_prometheus_metric(
                'github_flakiness_retest_rate_percent',
                {'repository': repo_name},
                summary.get('pr_retest_rate', 0),
                timestamp_ms
            ))
            metrics_batch.append(create_prometheus_metric(
                'github_flakiness_avg_retests_per_pr',
                {'repository': repo_name},
                summary.get('avg_retests_per_pr', 0),
                timestamp_ms
            ))

    # Add overall metrics
    overall = data.get('overall_summary', {})
    metrics_batch.append(create_prometheus_metric(
        'github_flakiness_prs_analyzed_total',
        {'repository': 'all_repositories'},
        overall.get('total_prs_analyzed', 0),
        timestamp_ms
    ))
    metrics_batch.append(create_prometheus_metric(
        'github_flakiness_retests_total',
        {'repository': 'all_repositories'},
        overall.get('total_retests', 0),
        timestamp_ms
    ))

    if overall.get('total_prs_analyzed', 0) > 0:
        metrics_batch.append(create_prometheus_metric(
            'github_flakiness_retest_rate_percent',
            {'repository': 'all_repositories'},
            overall.get('pr_retest_rate', 0),
            timestamp_ms
        ))
        metrics_batch.append(create_prometheus_metric(
            'github_flakiness_avg_retests_per_pr',
            {'repository': 'all_repositories'},
            overall.get('avg_retests_per_pr', 0),
            timestamp_ms
        ))

    print(f"✅ Added {len([m for m in metrics_batch if 'github' in m])} GitHub metrics")


def push_gitlab_metrics(metrics_batch: List[str], timestamp_ms: int):
    """Read GitLab flakiness JSON and add metrics to batch"""
    with open('gitlab_flakiness_7days.json', 'r') as f:
        data = json.load(f)

    # Process each project
    for project_name, project_data in data.get('projects', {}).items():
        summary = project_data.get('summary', {})

        # Add aggregated metrics
        metrics_batch.append(create_prometheus_metric(
            'gitlab_flakiness_mrs_analyzed_total',
            {'project': project_name},
            summary.get('total_mrs_analyzed', 0),
            timestamp_ms
        ))
        metrics_batch.append(create_prometheus_metric(
            'gitlab_flakiness_retests_total',
            {'project': project_name},
            summary.get('total_retests', 0),
            timestamp_ms
        ))

        if summary.get('total_mrs_analyzed', 0) > 0:
            metrics_batch.append(create_prometheus_metric(
                'gitlab_flakiness_retest_rate_percent',
                {'project': project_name},
                summary.get('mr_retest_rate', 0),
                timestamp_ms
            ))
            metrics_batch.append(create_prometheus_metric(
                'gitlab_flakiness_avg_retests_per_mr',
                {'project': project_name},
                summary.get('avg_retests_per_mr', 0),
                timestamp_ms
            ))

    # Add overall metrics
    overall = data.get('overall_summary', {})
    metrics_batch.append(create_prometheus_metric(
        'gitlab_flakiness_mrs_analyzed_total',
        {'project': 'all_projects'},
        overall.get('total_mrs_analyzed', 0),
        timestamp_ms
    ))
    metrics_batch.append(create_prometheus_metric(
        'gitlab_flakiness_retests_total',
        {'project': 'all_projects'},
        overall.get('total_retests', 0),
        timestamp_ms
    ))

    if overall.get('total_mrs_analyzed', 0) > 0:
        metrics_batch.append(create_prometheus_metric(
            'gitlab_flakiness_retest_rate_percent',
            {'project': 'all_projects'},
            overall.get('mr_retest_rate', 0),
            timestamp_ms
        ))
        metrics_batch.append(create_prometheus_metric(
            'gitlab_flakiness_avg_retests_per_mr',
            {'project': 'all_projects'},
            overall.get('avg_retests_per_mr', 0),
            timestamp_ms
        ))

    print(f"✅ Added {len([m for m in metrics_batch if 'gitlab' in m])} GitLab metrics")


def push_to_grafana(metrics_batch: List[str], url: str, username: str, password: str):
    """Push metrics to Grafana Cloud using Prometheus remote_write API"""

    # Grafana Cloud expects /api/prom/push endpoint for remote_write
    if not url.endswith('/api/prom/push'):
        # Handle both full URLs and base URLs
        if '/api/prom' in url:
            url = url.replace('/api/prom/api/v1/push', '/api/prom/push')
        else:
            url = f"{url.rstrip('/')}/api/prom/push"

    print(f"📡 Pushing {len(metrics_batch)} metrics to Grafana Cloud...")
    print(f"🔗 Endpoint: {url}")

    # Join all metrics
    payload = ''.join(metrics_batch)

    # Push using HTTP POST with basic auth
    response = requests.post(
        url,
        data=payload,
        auth=(username, password),
        headers={'Content-Type': 'text/plain'},
        timeout=30
    )

    if response.status_code in [200, 204]:
        print(f"✅ Successfully pushed {len(metrics_batch)} metrics to Grafana Cloud!")
        return True
    else:
        print(f"❌ Failed to push metrics. Status: {response.status_code}")
        print(f"Response: {response.text}")
        return False


if __name__ == '__main__':
    # Get Grafana Cloud credentials from environment
    grafana_url = os.getenv('GRAFANA_CLOUD_URL')
    grafana_user = os.getenv('GRAFANA_CLOUD_USER')
    grafana_token = os.getenv('GRAFANA_CLOUD_TOKEN')

    if not all([grafana_url, grafana_user, grafana_token]):
        print("❌ Missing Grafana Cloud credentials in environment variables!")
        print("Required: GRAFANA_CLOUD_URL, GRAFANA_CLOUD_USER, GRAFANA_CLOUD_TOKEN")
        sys.exit(1)

    # Use current timestamp
    timestamp_ms = int(time.time() * 1000)

    # Collect all metrics
    metrics_batch = []

    print("📊 Reading JSON files and preparing metrics...")
    push_github_metrics(metrics_batch, timestamp_ms)
    push_gitlab_metrics(metrics_batch, timestamp_ms)

    print(f"\n📦 Total metrics prepared: {len(metrics_batch)}")

    # Push to Grafana Cloud
    success = push_to_grafana(metrics_batch, grafana_url, grafana_user, grafana_token)

    sys.exit(0 if success else 1)
