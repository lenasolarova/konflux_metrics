#!/usr/bin/env python3
"""Helper to push Prometheus metrics to Grafana Cloud"""

import os
import time
import requests
from prometheus_client import CollectorRegistry
from prometheus_client.exposition import generate_latest


def push_to_grafana_cloud(registry, job_name='github-flakiness-analyzer'):
    """
    Push metrics from a Prometheus registry to Grafana Cloud using Pushgateway protocol

    Requires environment variables:
    - GRAFANA_CLOUD_PUSHGATEWAY_URL: e.g., https://prometheus-prod-65-prod-eu-west-2.grafana.net/api/prom/push
    - GRAFANA_CLOUD_USER: e.g., 2770427
    - GRAFANA_CLOUD_TOKEN: API token

    Note: We use prometheus_client's push_to_gateway which handles the format correctly
    """
    from prometheus_client import push_to_gateway

    pushgateway_url = os.environ.get('GRAFANA_CLOUD_URL')
    user = os.environ.get('GRAFANA_CLOUD_USER')
    token = os.environ.get('GRAFANA_CLOUD_TOKEN')

    if not all([pushgateway_url, user, token]):
        raise ValueError(
            "Missing Grafana Cloud credentials. Set GRAFANA_CLOUD_URL, "
            "GRAFANA_CLOUD_USER, and GRAFANA_CLOUD_TOKEN environment variables."
        )

    # Extract the host from the URL (remove https://)
    # Grafana Cloud Pushgateway URL format: https://prometheus-prod-XX-prod-YY.grafana.net/api/prom/push
    gateway_host = pushgateway_url.replace('https://', '').replace('http://', '')

    # Use push_to_gateway with basic auth
    # Format: username:password@host/path
    gateway_with_auth = f"{user}:{token}@{gateway_host}"

    try:
        push_to_gateway(gateway_with_auth, job=job_name, registry=registry)
        return True
    except Exception as e:
        print(f"Failed to push metrics to Grafana Cloud: {e}")
        raise
