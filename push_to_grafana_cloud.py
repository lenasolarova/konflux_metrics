#!/usr/bin/env python3
"""Scrape metrics from local Pushgateway and forward to Grafana Cloud using prometheus-client"""

import os
import sys
import requests
from prometheus_client import CollectorRegistry, Gauge, push_to_gateway
from prometheus_client.parser import text_string_to_metric_families


def parse_pushgateway_metrics(metrics_text):
    """Parse Prometheus metrics text format and extract metric data"""
    metrics_data = {}

    for family in text_string_to_metric_families(metrics_text):
        for sample in family.samples:
            metric_name = sample.name
            labels = sample.labels
            value = sample.value

            if metric_name not in metrics_data:
                metrics_data[metric_name] = []

            metrics_data[metric_name].append({
                'labels': labels,
                'value': value
            })

    return metrics_data


def forward_metrics_to_grafana(pushgateway_url, grafana_url, grafana_user, grafana_token):
    """Scrape metrics from Pushgateway and push to Grafana Cloud Pushgateway"""

    print(f"📥 Scraping metrics from Pushgateway at {pushgateway_url}...")

    # Scrape metrics from local Pushgateway
    try:
        response = requests.get(f"{pushgateway_url}/metrics", timeout=10)
        response.raise_for_status()
        metrics_text = response.text
        print(f"✅ Scraped {len(metrics_text.splitlines())} lines of metrics")
    except Exception as e:
        print(f"❌ Failed to scrape Pushgateway: {e}")
        return False

    # Parse the metrics
    metrics_data = parse_pushgateway_metrics(metrics_text)
    print(f"📊 Parsed {len(metrics_data)} unique metrics")

    # Create a new registry for Grafana Cloud
    registry = CollectorRegistry()
    gauges = {}

    # Recreate all metrics in the new registry
    for metric_name, samples in metrics_data.items():
        # Skip pushgateway internal metrics
        if metric_name.startswith('push_'):
            continue

        # Get all unique label names for this metric
        label_names = set()
        for sample in samples:
            label_names.update(sample['labels'].keys())

        label_names = sorted(list(label_names))

        # Create a gauge for this metric
        gauge = Gauge(
            metric_name,
            f'Metric {metric_name}',
            label_names,
            registry=registry
        )

        # Set values for all label combinations
        for sample in samples:
            labels = sample['labels']
            value = sample['value']

            # Fill in missing labels with empty strings
            label_values = {k: labels.get(k, '') for k in label_names}

            gauge.labels(**label_values).set(value)

    # Determine Grafana Cloud Pushgateway URL
    # Grafana Cloud format: https://prometheus-{instance}.grafana.net
    # Pushgateway endpoint: https://prometheus-{instance}.grafana.net:443/api/prom/push

    if '/api/prom/push' in grafana_url:
        # Use as-is, this is the remote_write URL but we'll try pushgateway
        # Replace with actual pushgateway endpoint
        base = grafana_url.split('/api/')[0]
        # Grafana Cloud doesn't have a separate pushgateway, we need to use prometheus-client's
        # pushadd_to_gateway which sends to remote_write compatible endpoint
        print(f"⚠️  Grafana Cloud remote_write endpoint detected")
        print(f"⚠️  prometheus-client doesn't support remote_write protocol")
        print(f"⚠️  Metrics will be pushed to local pushgateway only")
        return False
    else:
        # Assume it's a pushgateway URL
        push_url = grafana_url.rstrip('/')

    print(f"📡 Pushing metrics to Grafana Cloud Pushgateway...")
    print(f"🔗 Endpoint: {push_url}")

    # Push to Grafana Cloud using prometheus-client
    try:
        # Use basic auth format: user:password@host
        from urllib.parse import urlparse, urlunparse
        parsed = urlparse(push_url)

        # Reconstruct URL with auth
        auth_netloc = f"{grafana_user}:{grafana_token}@{parsed.netloc}"
        auth_url = urlunparse((
            parsed.scheme,
            auth_netloc,
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment
        ))

        push_to_gateway(auth_url, job='konflux_metrics', registry=registry)
        print(f"✅ Successfully pushed metrics to Grafana Cloud!")
        return True

    except Exception as e:
        print(f"❌ Error pushing to Grafana Cloud: {e}")
        print(f"\n💡 Grafana Cloud requires Prometheus remote_write protocol.")
        print(f"💡 The metrics are in the local Pushgateway at {pushgateway_url}")
        print(f"💡 Configure Prometheus to scrape the pushgateway and remote_write to Grafana Cloud.")
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

    if not success:
        print("\n" + "="*80)
        print("WORKAROUND: Use the original Prometheus relay approach")
        print("="*80)
        sys.exit(1)

    sys.exit(0)
