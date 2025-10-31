#!/usr/bin/env python3
"""Helper to push Prometheus metrics to Grafana Cloud using Remote Write"""

import os
import time
import base64
import requests


def push_to_grafana_cloud(registry, job_name='github-flakiness-analyzer'):
    """
    Push metrics to Grafana Cloud using Prometheus Remote Write protocol

    This uses the Influx write endpoint which accepts Prometheus exposition format

    Requires environment variables:
    - GRAFANA_CLOUD_URL: Remote write URL (e.g., https://prometheus-prod-65-prod-eu-west-2.grafana.net/api/prom/push)
    - GRAFANA_CLOUD_USER: Your instance ID (e.g., 2770427)
    - GRAFANA_CLOUD_TOKEN: Your Grafana Cloud API token
    """
    base_url = os.environ.get('GRAFANA_CLOUD_URL', '')
    user = os.environ.get('GRAFANA_CLOUD_USER')
    token = os.environ.get('GRAFANA_CLOUD_TOKEN')

    if not all([base_url, user, token]):
        print("⚠️  Grafana Cloud credentials not configured, skipping push")
        return False

    # Generate metrics in Prometheus exposition format
    from prometheus_client.exposition import generate_latest
    metrics_data = generate_latest(registry)

    # Parse metrics and convert to InfluxDB line protocol
    influx_lines = []
    current_time_ns = int(time.time() * 1e9)

    for line in metrics_data.decode('utf-8').split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        try:
            # Parse Prometheus format: metric_name{labels} value
            if '{' in line:
                metric_name, rest = line.split('{', 1)
                labels_str, value_str = rest.rsplit('}', 1)
                value = float(value_str.strip())

                # Parse labels into tags
                tags = [f'job={job_name}']
                if labels_str:
                    for label in labels_str.split(','):
                        if '=' in label:
                            key, val = label.split('=', 1)
                            tags.append(f'{key.strip()}={val.strip().strip(chr(34))}')

                # InfluxDB line protocol: measurement,tag1=val1,tag2=val2 field=value timestamp
                tag_str = ','.join(tags)
                influx_lines.append(f'{metric_name},{tag_str} value={value} {current_time_ns}')
            else:
                # No labels
                parts = line.split()
                if len(parts) >= 2:
                    metric_name = parts[0]
                    value = float(parts[1])
                    influx_lines.append(f'{metric_name},job={job_name} value={value} {current_time_ns}')
        except Exception as e:
            continue

    if not influx_lines:
        print("⚠️  No metrics to push")
        return False

    # Convert Grafana Cloud Prometheus URL to Influx endpoint
    # https://prometheus-xxx.grafana.net/api/prom/push -> https://influx-xxx.grafana.net/api/v1/push/influx/write
    influx_url = base_url.replace('/api/prom/push', '/api/v1/push/influx/write').replace('prometheus-', 'influx-')

    # Send to Grafana Cloud via Influx endpoint
    try:
        auth_str = f'{user}:{token}'
        auth_b64 = base64.b64encode(auth_str.encode()).decode()

        headers = {
            'Authorization': f'Basic {auth_b64}',
            'Content-Type': 'text/plain'
        }

        payload = '\n'.join(influx_lines)
        response = requests.post(influx_url, data=payload, headers=headers, timeout=10)

        if response.status_code in (200, 204):
            print(f"✅ Successfully pushed {len(influx_lines)} metrics to Grafana Cloud")
            return True
        else:
            print(f"❌ Failed to push metrics: {response.status_code}")
            print(f"   Response: {response.text[:200]}")
            return False

    except Exception as e:
        print(f"❌ Failed to push metrics to Grafana Cloud: {e}")
        return False
