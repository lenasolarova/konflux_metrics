#!/usr/bin/env python3
"""Analyze historical flakiness for merged PRs in the last 30 days"""

import json
import urllib.request
import urllib.error
from datetime import datetime, timedelta
import sys
import time
import os

# Prometheus imports
from prometheus_client import CollectorRegistry, Counter, Gauge, push_to_gateway

# Grafana Cloud support
try:
    from push_to_grafana_cloud import push_to_grafana_cloud
    GRAFANA_CLOUD_AVAILABLE = True
except ImportError:
    GRAFANA_CLOUD_AVAILABLE = False


class HistoricalFlakinessAnalyzer:
    def __init__(self, repo, token=None):
        self.repo = repo
        self.base_url = f"https://api.github.com/repos/{repo}"
        self.headers = {"Accept": "application/vnd.github.v3+json"}
        if token:
            self.headers["Authorization"] = f"token {token}"
        self.rate_limit_remaining = None

    def _api_request(self, url):
        """Make API request with rate limit handling"""
        req = urllib.request.Request(url, headers=self.headers)
        try:
            with urllib.request.urlopen(req) as response:
                self.rate_limit_remaining = int(response.headers.get('X-RateLimit-Remaining', 0))
                return json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            if e.code == 403 and 'rate limit' in str(e.read().decode('utf-8')).lower():
                print(f"⚠️  Rate limit exceeded. Waiting 60 seconds...")
                time.sleep(60)
                return self._api_request(url)  # Retry
            print(f"Error: {e.code} - {e.reason}")
            raise

    def get_merged_prs(self, since_date):
        """Get all PRs merged since a given date"""
        prs = []
        page = 1

        while True:
            url = f"{self.base_url}/pulls?state=closed&sort=updated&direction=desc&per_page=100&page={page}"
            data = self._api_request(url)

            if not data:
                break

            for pr in data:
                # Check if merged
                if not pr.get('merged_at'):
                    continue

                merged_at = datetime.fromisoformat(pr['merged_at'].replace('Z', '+00:00'))

                # Stop if we've gone past our date range
                if merged_at < since_date:
                    return prs

                prs.append({
                    'number': pr['number'],
                    'title': pr['title'],
                    'merged_at': pr['merged_at'],
                    'user': pr['user']['login']
                })

            page += 1

            # GitHub API pagination limit
            if page > 10:
                break

        return prs

    def get_check_suites(self, commit_sha):
        """Get check suites for a commit"""
        url = f"{self.base_url}/commits/{commit_sha}/check-suites"
        return self._api_request(url)

    def get_konflux_rerun_count(self, commit_sha):
        """Count how many times the Konflux on-pull-request suite ran for this commit

        Counts multiple check suite INSTANCES (not check runs within a suite).
        When someone clicks "Re-run", GitHub creates a NEW check suite instance.
        We count these instances to detect reruns.

        Returns: Total number of Konflux suite runs (including original + reruns)
        """
        data = self.get_check_suites(commit_sha)

        # Count how many Konflux "on-pull-request" check suite INSTANCES exist
        konflux_suite_count = 0

        for suite in data.get('check_suites', []):
            app = suite.get('app', {})
            # Only count Konflux suites with "on-pull-request" in the name
            if app.get('slug') == 'red-hat-konflux':
                # Check if this is the on-pull-request suite
                # (Some repos might have multiple Konflux suites for different triggers)
                suite_name = suite.get('app', {}).get('name', '')
                # Count all Konflux suites (they should all be on-pull-request for merged PRs)
                konflux_suite_count += 1

        return konflux_suite_count

    def get_pr_commits(self, pr_number):
        """Get commits for a PR"""
        url = f"{self.base_url}/pulls/{pr_number}/commits"
        commits = self._api_request(url)
        return [commit['sha'] for commit in commits]

    def analyze_pr(self, pr_info):
        """Analyze flakiness for a single PR"""
        pr_number = pr_info['number']

        try:
            commits = self.get_pr_commits(pr_number)
        except Exception as e:
            print(f"    ⚠️  Error fetching commits: {e}")
            return None

        total_runs = 0
        total_retests = 0
        commits_with_retests = 0

        for sha in commits:
            try:
                # Get total run count (including reruns) from check suite
                run_count = self.get_konflux_rerun_count(sha)
                # Reruns = total runs - 1 (original)
                retest_count = max(0, run_count - 1)

                total_runs += run_count
                total_retests += retest_count

                if retest_count > 0:
                    commits_with_retests += 1

            except Exception as e:
                print(f"    ⚠️  Error analyzing commit {sha[:8]}: {e}")
                continue

        return {
            'pr_number': pr_number,
            'title': pr_info['title'],
            'merged_at': pr_info['merged_at'],
            'user': pr_info['user'],
            'total_commits': len(commits),
            'total_runs': total_runs,
            'total_retests': total_retests,
            'commits_with_retests': commits_with_retests,
        }


def setup_prometheus_metrics():
    """Initialize Prometheus metrics registry and metrics"""
    registry = CollectorRegistry()

    # Per-PR metrics with pr_number label
    pr_retests = Gauge(
        'github_pr_retests',
        'Number of retests for individual PR',
        ['repository', 'pr_number', 'author'],
        registry=registry
    )

    # Aggregated metrics per repository
    retests_total = Gauge(
        'github_flakiness_retests_total',
        'Total number of retests detected',
        ['repository'],
        registry=registry
    )

    retest_rate = Gauge(
        'github_flakiness_retest_rate_percent',
        'Percentage of PRs requiring retests',
        ['repository'],
        registry=registry
    )

    avg_retests_per_pr = Gauge(
        'github_flakiness_avg_retests_per_pr',
        'Average number of retests per PR',
        ['repository'],
        registry=registry
    )

    prs_analyzed_total = Gauge(
        'github_flakiness_prs_analyzed_total',
        'Total number of pull requests analyzed',
        ['repository'],
        registry=registry
    )

    return registry, {
        'pr_retests': pr_retests,
        'retests_total': retests_total,
        'retest_rate': retest_rate,
        'avg_retests_per_pr': avg_retests_per_pr,
        'prs_analyzed': prs_analyzed_total,
    }


def main():
    # Configuration
    repos = [
        "RedHatInsights/insights-ccx-messaging",
        "RedHatInsights/insights-results-aggregator",
        "RedHatInsights/insights-results-aggregator-exporter",
        "RedHatInsights/insights-content-template-renderer",
        "RedHatInsights/insights-behavioral-spec",
        "RedHatInsights/insights-results-aggregator-cleaner",
        "RedHatInsights/insights-operator-gathering-conditions-service",
        "RedHatInsights/ccx-notification-service",
        "RedHatInsights/ccx-notification-writer",
        "RedHatInsights/obsint-mocks",
        "RedHatInsights/insights-results-smart-proxy"
    ]
    days_back = 7  # Analyze last week by default

    # Prometheus Pushgateway configuration
    pushgateway_url = os.environ.get('PROMETHEUS_PUSHGATEWAY', 'localhost:9091')

    # Initialize Prometheus metrics
    registry, prom_metrics = setup_prometheus_metrics()

    # Get token from environment or use None (rate limited to 60/hour)
    token = os.environ.get('GITHUB_TOKEN')

    if not token:
        print("⚠️  No GITHUB_TOKEN found. Using unauthenticated requests (60/hour limit)")
        print("   Set GITHUB_TOKEN environment variable for higher rate limit (5000/hour)")
        print()

    # Calculate date range (timezone-aware)
    from datetime import timezone
    since_date = datetime.now(timezone.utc) - timedelta(days=days_back)

    # Store results for all repos
    all_results = {}

    for repo in repos:
        print(f"\nAnalyzing {repo} ({since_date.strftime('%Y-%m-%d')} to {datetime.now().strftime('%Y-%m-%d')})...")

        # Initialize analyzer for this repo
        analyzer = HistoricalFlakinessAnalyzer(repo, token)

        # Get merged PRs
        try:
            prs = analyzer.get_merged_prs(since_date)
        except Exception as e:
            print(f"  ❌ Error: {e}")
            continue

        if not prs:
            print("No merged PRs found for this repo.")
            all_results[repo] = {
                'prs': [],
                'summary': {
                    'total_prs_analyzed': 0,
                    'total_commits': 0,
                    'total_runs': 0,
                    'total_retests': 0,
                    'prs_with_retests': 0,
                    'pr_retest_rate': 0,
                    'avg_retests_per_pr': 0,
                    'avg_retests_per_commit': 0,
                }
            }
            continue

        # Analyze each PR
        results = []
        total_prs = len(prs)

        for idx, pr_info in enumerate(prs, 1):
            result = analyzer.analyze_pr(pr_info)
            if result:
                results.append(result)

            # Rate limiting courtesy
            if analyzer.rate_limit_remaining and analyzer.rate_limit_remaining < 10:
                print(f"    ⏸  Rate limit low ({analyzer.rate_limit_remaining}), waiting 10 seconds...")
                time.sleep(10)

        # Calculate statistics for this repo
        total_prs_analyzed = len(results)
        total_commits = sum(r['total_commits'] for r in results)
        total_runs = sum(r['total_runs'] for r in results)
        total_retests = sum(r['total_retests'] for r in results)
        prs_with_retests = sum(1 for r in results if r['total_retests'] > 0)

        print(f"  {total_prs_analyzed} PRs, {total_retests} retests ({prs_with_retests/total_prs_analyzed*100:.1f}% rate)" if total_prs_analyzed > 0 else "  No PRs analyzed")

        # Store results for this repo
        all_results[repo] = {
            'prs': results,
            'summary': {
                'total_prs_analyzed': total_prs_analyzed,
                'total_commits': total_commits,
                'total_runs': total_runs,
                'total_retests': total_retests,
                'prs_with_retests': prs_with_retests,
                'pr_retest_rate': prs_with_retests/total_prs_analyzed*100 if total_prs_analyzed > 0 else 0,
                'avg_retests_per_pr': total_retests/total_prs_analyzed if total_prs_analyzed > 0 else 0,
                'avg_retests_per_commit': total_retests/total_commits if total_commits > 0 else 0,
            }
        }

        # Record per-PR metrics
        for pr in results:
            prom_metrics['pr_retests'].labels(
                repository=repo,
                pr_number=str(pr['pr_number']),
                author=pr['user']
            ).set(pr['total_retests'])

        # Record aggregated metrics for this repo
        prom_metrics['prs_analyzed'].labels(repository=repo).set(total_prs_analyzed)
        prom_metrics['retests_total'].labels(repository=repo).set(total_retests)

        if total_prs_analyzed > 0:
            prom_metrics['retest_rate'].labels(repository=repo).set(prs_with_retests/total_prs_analyzed*100)
            prom_metrics['avg_retests_per_pr'].labels(repository=repo).set(total_retests/total_prs_analyzed)

    # Overall summary
    overall_prs = sum(repo['summary']['total_prs_analyzed'] for repo in all_results.values())
    overall_commits = sum(repo['summary']['total_commits'] for repo in all_results.values())
    overall_runs = sum(repo['summary']['total_runs'] for repo in all_results.values())
    overall_retests = sum(repo['summary']['total_retests'] for repo in all_results.values())
    overall_prs_with_retests = sum(repo['summary']['prs_with_retests'] for repo in all_results.values())

    print(f"\n📊 Total: {overall_prs} PRs, {overall_retests} retests ({overall_prs_with_retests/overall_prs*100:.1f}% rate)" if overall_prs > 0 else "\n📊 No PRs analyzed")

    # Save results
    output_file = f"github_flakiness_{days_back}days.json"
    summary_data = {
        'analysis_date': datetime.now().isoformat(),
        'repos': list(repos),
        'days_analyzed': days_back,
        'date_range': {
            'from': since_date.isoformat(),
            'to': datetime.now().isoformat()
        },
        'overall_summary': {
            'total_repos': len(all_results),
            'total_prs_analyzed': overall_prs,
            'total_commits': overall_commits,
            'total_runs': overall_runs,
            'total_retests': overall_retests,
            'prs_with_retests': overall_prs_with_retests,
            'pr_retest_rate': overall_prs_with_retests/overall_prs*100 if overall_prs > 0 else 0,
            'avg_retests_per_pr': overall_retests/overall_prs if overall_prs > 0 else 0,
            'avg_retests_per_commit': overall_retests/overall_commits if overall_commits > 0 else 0,
        },
        'repositories': all_results
    }

    with open(output_file, 'w') as f:
        json.dump(summary_data, f, indent=2)

    print(f"\n💾 Detailed results saved to: {output_file}")

    # Record overall metrics
    prom_metrics['prs_analyzed'].labels(repository='all_repos').set(overall_prs)
    prom_metrics['retests_total'].labels(repository='all_repos').set(overall_retests)

    if overall_prs > 0:
        prom_metrics['retest_rate'].labels(repository='all_repos').set(overall_prs_with_retests/overall_prs*100)
        prom_metrics['avg_retests_per_pr'].labels(repository='all_repos').set(overall_retests/overall_prs)

    # Push metrics to Prometheus (Pushgateway or Grafana Cloud)
    grafana_cloud_url = os.environ.get('GRAFANA_CLOUD_URL')

    if grafana_cloud_url and GRAFANA_CLOUD_AVAILABLE:
        # Push to Grafana Cloud
        print(f"\n📊 Pushing metrics to Grafana Cloud...")
        try:
            push_to_grafana_cloud(registry, job_name='github-flakiness-analyzer')
            print("✅ Metrics successfully pushed to Grafana Cloud!")
        except Exception as e:
            print(f"⚠️  Failed to push metrics to Grafana Cloud: {e}")
            print("   Continuing anyway...")
    elif pushgateway_url:
        # Push to local Pushgateway
        print(f"\n📊 Pushing metrics to Prometheus Pushgateway at {pushgateway_url}...")
        try:
            push_to_gateway(pushgateway_url, job='github-flakiness-analyzer', registry=registry)
            print("✅ Metrics successfully pushed to Prometheus!")
        except Exception as e:
            print(f"⚠️  Failed to push metrics to Prometheus: {e}")
            print("   Continuing anyway...")
    else:
        print("\n⚠️  No Prometheus endpoint configured (set GRAFANA_CLOUD_URL or PROMETHEUS_PUSHGATEWAY)")

    print("\n✅ Analysis complete!")


if __name__ == "__main__":
    main()
