#!/usr/bin/env python3
"""Helper to push Prometheus metrics to Grafana Cloud"""

import os
from prometheus_client import push_to_gateway


def push_to_grafana_cloud(registry, job_name='github-flakiness-analyzer'):
    """
    Push metrics directly to Grafana Cloud's Prometheus Pushgateway

    Grafana Cloud provides a Pushgateway-compatible endpoint at:
    https://<instance-id>:<token>@prometheus-<region>.grafana.net/api/prom/push

    Requires environment variables:
    - GRAFANA_CLOUD_URL: Full Prometheus URL (e.g., https://prometheus-prod-65-prod-eu-west-2.grafana.net/api/prom/push)
    - GRAFANA_CLOUD_USER: Your Grafana Cloud instance ID (e.g., 2770427)
    - GRAFANA_CLOUD_TOKEN: Your Grafana Cloud API token
    """
    base_url = os.environ.get('GRAFANA_CLOUD_URL', '')
    user = os.environ.get('GRAFANA_CLOUD_USER')
    token = os.environ.get('GRAFANA_CLOUD_TOKEN')

    if not all([base_url, user, token]):
        raise ValueError(
            "Missing Grafana Cloud credentials. Set GRAFANA_CLOUD_URL, "
            "GRAFANA_CLOUD_USER, and GRAFANA_CLOUD_TOKEN environment variables."
        )

    # Extract host from URL
    # Input: https://prometheus-prod-65-prod-eu-west-2.grafana.net/api/prom/push
    # Need: <user>:<token>@prometheus-prod-65-prod-eu-west-2.grafana.net/api/prom/push

    import urllib.parse
    parsed = urllib.parse.urlparse(base_url)

    # Build the gateway URL with embedded credentials
    # Format for push_to_gateway: user:password@host:port/path
    gateway_url = f"{user}:{token}@{parsed.netloc}{parsed.path}"

    try:
        # Use prometheus_client's push_to_gateway with the authenticated URL
        push_to_gateway(gateway_url, job=job_name, registry=registry)
        return True
    except Exception as e:
        print(f"Failed to push metrics to Grafana Cloud: {e}")
        raise
