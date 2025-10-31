#!/usr/bin/env python3
"""Helper to push Prometheus metrics to Grafana Cloud"""

import os
import time
import requests
from prometheus_client import CollectorRegistry
from prometheus_client.exposition import generate_latest


def push_to_grafana_cloud(registry, job_name='github-flakiness-analyzer'):
    """
    Push metrics from a Prometheus registry to Grafana Cloud

    Requires environment variables:
    - GRAFANA_CLOUD_URL: e.g., https://prometheus-prod-65-prod-eu-west-2.grafana.net/api/prom/push
    - GRAFANA_CLOUD_USER: e.g., 2770427
    - GRAFANA_CLOUD_TOKEN: API token
    """
    url = os.environ.get('GRAFANA_CLOUD_URL')
    user = os.environ.get('GRAFANA_CLOUD_USER')
    token = os.environ.get('GRAFANA_CLOUD_TOKEN')

    if not all([url, user, token]):
        raise ValueError(
            "Missing Grafana Cloud credentials. Set GRAFANA_CLOUD_URL, "
            "GRAFANA_CLOUD_USER, and GRAFANA_CLOUD_TOKEN environment variables."
        )

    # Generate metrics in Prometheus exposition format
    metrics_data = generate_latest(registry)

    # Add job label to all metrics
    # Convert bytes to string, add job label, convert back
    metrics_str = metrics_data.decode('utf-8')

    # Post to Grafana Cloud using remote write endpoint
    # Note: Grafana Cloud accepts Prometheus exposition format at the push endpoint
    headers = {
        'Content-Type': 'text/plain; version=0.0.4',
    }

    try:
        response = requests.post(
            url,
            auth=(user, token),
            data=metrics_data,
            headers=headers,
            timeout=30
        )
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        print(f"Failed to push metrics to Grafana Cloud: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response: {e.response.text}")
        raise
