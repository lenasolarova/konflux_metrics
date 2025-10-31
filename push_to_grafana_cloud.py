#!/usr/bin/env python3
"""Scrape metrics from local Pushgateway and forward to Grafana Cloud"""

import os
import sys
import requests


def forward_metrics_to_grafana(pushgateway_url, grafana_url, grafana_user, grafana_token):
    """Scrape metrics from Pushgateway and push to Grafana Cloud"""

    print(f"📥 Scraping metrics from Pushgateway at {pushgateway_url}...")

    # Scrape metrics from Pushgateway
    try:
        response = requests.get(f"{pushgateway_url}/metrics", timeout=10)
        response.raise_for_status()
        metrics_data = response.text
        print(f"✅ Scraped {len(metrics_data.splitlines())} lines of metrics")
    except Exception as e:
        print(f"❌ Failed to scrape Pushgateway: {e}")
        return False

    # Determine the correct Grafana Cloud endpoint
    # Grafana Cloud supports Pushgateway format at /api/v1/push
    if '/api/prom/push' in grafana_url:
        # Convert remote_write URL to pushgateway URL
        base_url = grafana_url.replace('/api/prom/push', '')
        push_url = f"{base_url}/api/v1/push/metrics/job/konflux_metrics"
    else:
        push_url = f"{grafana_url.rstrip('/')}/api/v1/push/metrics/job/konflux_metrics"

    print(f"📡 Pushing metrics to Grafana Cloud...")
    print(f"🔗 Endpoint: {push_url}")

    # Push to Grafana Cloud
    try:
        response = requests.post(
            push_url,
            data=metrics_data.encode('utf-8'),
            auth=(grafana_user, grafana_token),
            headers={'Content-Type': 'text/plain; version=0.0.4'},
            timeout=30
        )

        if response.status_code in [200, 202, 204]:
            print(f"✅ Successfully pushed metrics to Grafana Cloud!")
            return True
        else:
            print(f"❌ Failed to push metrics. Status: {response.status_code}")
            print(f"Response: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Error pushing to Grafana Cloud: {e}")
        return False


if __name__ == '__main__':
    # Get configuration from environment
    pushgateway_url = os.getenv('PUSHGATEWAY_URL', 'http://localhost:9091')
    grafana_url = os.getenv('GRAFANA_CLOUD_URL')
    grafana_user = os.getenv('GRAFANA_CLOUD_USER')
    grafana_token = os.getenv('GRAFANA_CLOUD_TOKEN')

    if not all([grafana_url, grafana_user, grafana_token]):
        print("❌ Missing Grafana Cloud credentials in environment variables!")
        print("Required: GRAFANA_CLOUD_URL, GRAFANA_CLOUD_USER, GRAFANA_CLOUD_TOKEN")
        sys.exit(1)

    # Forward metrics
    success = forward_metrics_to_grafana(pushgateway_url, grafana_url, grafana_user, grafana_token)

    sys.exit(0 if success else 1)
