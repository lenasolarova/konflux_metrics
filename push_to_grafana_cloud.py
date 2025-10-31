#!/usr/bin/env python3
"""Helper to push Prometheus metrics to Grafana Cloud using Remote Write"""

import os
import time


def push_to_grafana_cloud(registry, job_name='github-flakiness-analyzer'):
    """
    Push metrics to Grafana Cloud using Prometheus Remote Write protocol

    Uses prometheus-remote-write library which handles protobuf + snappy compression

    Requires environment variables:
    - GRAFANA_CLOUD_URL: Remote write URL (e.g., https://prometheus-prod-65-prod-eu-west-2.grafana.net/api/prom/push)
    - GRAFANA_CLOUD_USER: Your instance ID (e.g., 2770427)
    - GRAFANA_CLOUD_TOKEN: Your Grafana Cloud API token
    """
    try:
        from prometheus_remote_write import RemoteWriteClient
    except ImportError:
        print("prometheus-remote-write not installed, skipping Grafana Cloud push")
        return False

    base_url = os.environ.get('GRAFANA_CLOUD_URL', '')
    user = os.environ.get('GRAFANA_CLOUD_USER')
    token = os.environ.get('GRAFANA_CLOUD_TOKEN')

    if not all([base_url, user, token]):
        raise ValueError(
            "Missing Grafana Cloud credentials. Set GRAFANA_CLOUD_URL, "
            "GRAFANA_CLOUD_USER, and GRAFANA_CLOUD_TOKEN environment variables."
        )

    # Parse metrics from registry
    from prometheus_client.exposition import generate_latest
    metrics_data = generate_latest(registry).decode('utf-8')

    # Build timeseries for remote write
    timeseries = []
    current_time_ms = int(time.time() * 1000)

    for line in metrics_data.split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        try:
            # Parse metric name, labels, and value
            if '{' in line:
                metric_name, rest = line.split('{', 1)
                labels_str, value_str = rest.rsplit('}', 1)
                value = float(value_str.strip())

                # Parse labels
                labels = {'__name__': metric_name, 'job': job_name}
                if labels_str:
                    for label in labels_str.split(','):
                        if '=' in label:
                            key, val = label.split('=', 1)
                            labels[key.strip()] = val.strip().strip('"')
            else:
                # No labels
                parts = line.split()
                if len(parts) >= 2:
                    metric_name = parts[0]
                    value = float(parts[1])
                    labels = {'__name__': metric_name, 'job': job_name}
                else:
                    continue

            timeseries.append({
                'labels': labels,
                'samples': [{'value': value, 'timestamp': current_time_ms}]
            })
        except Exception:
            continue

    if not timeseries:
        print("No metrics to push")
        return False

    # Create remote write client and send
    try:
        client = RemoteWriteClient(
            url=base_url,
            username=user,
            password=token,
            timeout=10
        )
        client.write(timeseries)
        return True
    except Exception as e:
        print(f"Failed to push metrics to Grafana Cloud: {e}")
        raise
