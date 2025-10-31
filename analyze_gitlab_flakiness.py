#!/usr/bin/env python3
"""Analyze flakiness for GitLab repos with Konflux pipelines"""

import json
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
import sys
import time
import os
import ssl

# Prometheus imports
from prometheus_client import CollectorRegistry, Counter, Gauge, push_to_gateway

# Grafana Cloud support
try:
    from push_to_grafana_cloud import push_to_grafana_cloud
    GRAFANA_CLOUD_AVAILABLE = True
except ImportError:
    GRAFANA_CLOUD_AVAILABLE = False


class GitLabFlakinessAnalyzer:
    def __init__(self, gitlab_url, project_path, token=None):
        """
        Args:
            gitlab_url: GitLab instance URL (e.g., "https://gitlab.cee.redhat.com")
            project_path: Project path (e.g., "insights-qe/iqe-ccx-plugin")
            token: GitLab personal access token
        """
        self.gitlab_url = gitlab_url.rstrip('/')
        self.project_path = project_path
        # URL encode the project path (/ becomes %2F)
        self.project_id = project_path.replace('/', '%2F')
        self.api_base = f"{self.gitlab_url}/api/v4"

        self.headers = {"Accept": "application/json"}
        if token:
            self.headers["PRIVATE-TOKEN"] = token

        self.rate_limit_remaining = None

    def _api_request(self, url):
        """Make API request with error handling"""
        req = urllib.request.Request(url, headers=self.headers)
        # Disable SSL verification for internal GitLab with self-signed cert
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            with urllib.request.urlopen(req, context=ctx) as response:
                # GitLab uses RateLimit-Remaining header
                self.rate_limit_remaining = response.headers.get('RateLimit-Remaining')
                return json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8')
            print(f"❌ HTTP Error {e.code}: {e.reason}")
            print(f"   URL: {url}")
            print(f"   Response: {error_body[:200]}")
            raise
        except urllib.error.URLError as e:
            print(f"❌ URL Error: {e.reason}")
            print(f"   URL: {url}")
            raise

    def get_merged_mrs(self, since_date):
        """Get merged MRs (Merge Requests) since a given date"""
        mrs = []
        page = 1

        while True:
            # GitLab API: Get MRs that were merged
            url = (f"{self.api_base}/projects/{self.project_id}/merge_requests"
                   f"?state=merged&order_by=updated_at&sort=desc"
                   f"&per_page=100&page={page}")

            try:
                data = self._api_request(url)
            except Exception as e:
                break

            if not data:
                break

            for mr in data:
                merged_at_str = mr.get('merged_at')
                if not merged_at_str:
                    continue

                # Parse GitLab datetime format
                merged_at = datetime.fromisoformat(merged_at_str.replace('Z', '+00:00'))

                # Stop if we've gone past our date range
                if merged_at < since_date:
                    return mrs

                mrs.append({
                    'iid': mr['iid'],  # GitLab uses 'iid' (internal ID)
                    'title': mr['title'],
                    'merged_at': merged_at_str,
                    'author': mr['author']['username'],
                    'source_branch': mr['source_branch'],
                    'target_branch': mr['target_branch'],
                })

            page += 1

            # Safety limit
            if page > 10:
                break

        return mrs

    def get_mr_commits(self, mr_iid):
        """Get commits for an MR"""
        url = f"{self.api_base}/projects/{self.project_id}/merge_requests/{mr_iid}/commits"

        try:
            commits = self._api_request(url)
            return [commit['id'] for commit in commits]
        except Exception as e:
            print(f"    ⚠️  Error fetching commits: {e}")
            return []

    def get_commit_pipelines(self, commit_sha):
        """Get pipelines for a commit"""
        url = f"{self.api_base}/projects/{self.project_id}/pipelines?sha={commit_sha}"

        try:
            pipelines = self._api_request(url)
            return pipelines
        except Exception as e:
            print(f"    ⚠️  Error fetching pipelines: {e}")
            return []

    def filter_konflux_pipelines(self, pipelines):
        """Filter pipelines to only include Konflux on-pull-request runs"""
        konflux_runs = []

        for pipeline in pipelines:
            # Check if this is a Konflux pipeline
            # Konflux pipelines typically have specific naming or source
            ref = pipeline.get('ref', '')
            source = pipeline.get('source', '')

            # Look for patterns that indicate Konflux on-pull-request pipelines
            # Adjust these filters based on actual pipeline naming in your repo
            if any([
                'pull-request' in ref.lower(),
                'merge-request' in ref.lower(),
                source == 'merge_request_event',
                source == 'external_pull_request_event',
            ]):
                konflux_runs.append({
                    'id': pipeline['id'],
                    'ref': pipeline['ref'],
                    'sha': pipeline['sha'],
                    'status': pipeline['status'],
                    'source': pipeline.get('source'),
                    'web_url': pipeline.get('web_url'),
                    'created_at': pipeline.get('created_at'),
                })

        return konflux_runs

    def analyze_mr(self, mr_info):
        """Analyze flakiness for a single MR"""
        mr_iid = mr_info['iid']

        try:
            commits = self.get_mr_commits(mr_iid)
        except Exception as e:
            print(f"    ⚠️  Error fetching commits: {e}")
            return None

        if not commits:
            return None

        total_pipelines = 0
        total_retests = 0
        commits_with_retests = 0

        for sha in commits:
            try:
                # Get all pipelines for this commit
                pipelines = self.get_commit_pipelines(sha)

                # Filter to Konflux on-pull-request pipelines
                konflux_pipelines = self.filter_konflux_pipelines(pipelines)

                pipeline_count = len(konflux_pipelines)
                retest_count = max(0, pipeline_count - 1)

                total_pipelines += pipeline_count
                total_retests += retest_count

                if retest_count > 0:
                    commits_with_retests += 1

            except Exception as e:
                print(f"    ⚠️  Error analyzing commit {sha[:8]}: {e}")
                continue

        return {
            'mr_iid': mr_iid,
            'title': mr_info['title'],
            'merged_at': mr_info['merged_at'],
            'author': mr_info['author'],
            'total_commits': len(commits),
            'total_pipelines': total_pipelines,
            'total_retests': total_retests,
            'commits_with_retests': commits_with_retests,
        }


def setup_prometheus_metrics():
    """Initialize Prometheus metrics registry and metrics"""
    registry = CollectorRegistry()

    # Per-MR metrics with mr_number label
    mr_retests = Gauge(
        'gitlab_mr_retests',
        'Number of retests for individual MR',
        ['project', 'mr_number', 'author'],
        registry=registry
    )

    # Aggregated metrics per project
    retests_total = Gauge(
        'gitlab_flakiness_retests_total',
        'Total number of retests detected',
        ['project'],
        registry=registry
    )

    retest_rate = Gauge(
        'gitlab_flakiness_retest_rate_percent',
        'Percentage of MRs requiring retests',
        ['project'],
        registry=registry
    )

    avg_retests_per_mr = Gauge(
        'gitlab_flakiness_avg_retests_per_mr',
        'Average number of retests per MR',
        ['project'],
        registry=registry
    )

    mrs_analyzed_total = Gauge(
        'gitlab_flakiness_mrs_analyzed_total',
        'Total number of merge requests analyzed',
        ['project'],
        registry=registry
    )

    return registry, {
        'mr_retests': mr_retests,
        'retests_total': retests_total,
        'retest_rate': retest_rate,
        'avg_retests_per_mr': avg_retests_per_mr,
        'mrs_analyzed': mrs_analyzed_total,
    }


def main():
    # Configuration
    gitlab_url = "https://gitlab.cee.redhat.com"
    project_paths = [
        "insights-qe/iqe-ccx-plugin",
        "ccx/ccx-data-pipeline",
        "ccx/content-service",
        "ccx/ccx-load-test",
        "ccx/parquet-factory",
        "ccx/ccx-upgrades-data-eng",
        "ccx/ccx-upgrades-inference"
    ]
    days_back = 7  # Analyze last week by default

    # Prometheus Pushgateway configuration
    pushgateway_url = os.environ.get('PROMETHEUS_PUSHGATEWAY', 'localhost:9091')

    # Initialize Prometheus metrics
    registry, prom_metrics = setup_prometheus_metrics()

    # Get token from environment and strip any BOM or whitespace
    token = os.environ.get('GITLAB_TOKEN')
    if token:
        token = token.strip().lstrip('\ufeff')

    if not token:
        print("⚠️  No GITLAB_TOKEN found. You may hit rate limits or access restrictions.")
        print("   Set GITLAB_TOKEN environment variable with your GitLab personal access token")
        print("   Create one at: https://gitlab.cee.redhat.com/-/profile/personal_access_tokens")
        print("   Required scopes: read_api")
        print()
        response = input("Continue without token? (y/N): ")
        if response.lower() != 'y':
            print("Exiting. Please set GITLAB_TOKEN and try again.")
            sys.exit(1)
        print()

    # Calculate date range
    since_date = datetime.now(timezone.utc) - timedelta(days=days_back)

    # Store results for all projects
    all_results = {}

    for project_path in project_paths:
        print(f"\nAnalyzing {project_path} ({since_date.strftime('%Y-%m-%d')} to {datetime.now().strftime('%Y-%m-%d')})...")

        # Initialize analyzer for this project
        analyzer = GitLabFlakinessAnalyzer(gitlab_url, project_path, token)

        # Get merged MRs
        try:
            mrs = analyzer.get_merged_mrs(since_date)
        except Exception as e:
            print(f"  ❌ Error: {e}")
            continue

        if not mrs:
            print("No merged MRs found for this project.")
            all_results[project_path] = {
                'mrs': [],
                'summary': {
                    'total_mrs_analyzed': 0,
                    'total_commits': 0,
                    'total_pipelines': 0,
                    'total_retests': 0,
                    'mrs_with_retests': 0,
                    'mr_retest_rate': 0,
                    'avg_retests_per_mr': 0,
                    'avg_retests_per_commit': 0,
                }
            }
            continue

        # Analyze each MR
        results = []
        total_mrs = len(mrs)

        for idx, mr_info in enumerate(mrs, 1):
            result = analyzer.analyze_mr(mr_info)
            if result:
                results.append(result)

        # Calculate statistics for this project
        total_mrs_analyzed = len(results)
        total_commits = sum(r['total_commits'] for r in results)
        total_pipelines = sum(r['total_pipelines'] for r in results)
        total_retests = sum(r['total_retests'] for r in results)
        mrs_with_retests = sum(1 for r in results if r['total_retests'] > 0)

        print(f"  {total_mrs_analyzed} MRs, {total_retests} retests ({mrs_with_retests/total_mrs_analyzed*100:.1f}% rate)" if total_mrs_analyzed > 0 else "  No MRs analyzed")

        # Store results for this project
        all_results[project_path] = {
            'mrs': results,
            'summary': {
                'total_mrs_analyzed': total_mrs_analyzed,
                'total_commits': total_commits,
                'total_pipelines': total_pipelines,
                'total_retests': total_retests,
                'mrs_with_retests': mrs_with_retests,
                'mr_retest_rate': mrs_with_retests/total_mrs_analyzed*100 if total_mrs_analyzed > 0 else 0,
                'avg_retests_per_mr': total_retests/total_mrs_analyzed if total_mrs_analyzed > 0 else 0,
                'avg_retests_per_commit': total_retests/total_commits if total_commits > 0 else 0,
            }
        }

        # Record per-MR metrics
        for mr in results:
            prom_metrics['mr_retests'].labels(
                project=project_path,
                mr_number=str(mr['mr_iid']),
                author=mr['author']
            ).set(mr['total_retests'])

        # Record aggregated metrics for this project
        prom_metrics['mrs_analyzed'].labels(project=project_path).set(total_mrs_analyzed)
        prom_metrics['retests_total'].labels(project=project_path).set(total_retests)

        if total_mrs_analyzed > 0:
            prom_metrics['retest_rate'].labels(project=project_path).set(mrs_with_retests/total_mrs_analyzed*100)
            prom_metrics['avg_retests_per_mr'].labels(project=project_path).set(total_retests/total_mrs_analyzed)

    # Overall summary
    overall_mrs = sum(proj['summary']['total_mrs_analyzed'] for proj in all_results.values())
    overall_commits = sum(proj['summary']['total_commits'] for proj in all_results.values())
    overall_pipelines = sum(proj['summary']['total_pipelines'] for proj in all_results.values())
    overall_retests = sum(proj['summary']['total_retests'] for proj in all_results.values())
    overall_mrs_with_retests = sum(proj['summary']['mrs_with_retests'] for proj in all_results.values())

    print(f"\n📊 Total: {overall_mrs} MRs, {overall_retests} retests ({overall_mrs_with_retests/overall_mrs*100:.1f}% rate)" if overall_mrs > 0 else "\n📊 No MRs analyzed")

    # Save results
    output_file = f"gitlab_flakiness_{days_back}days.json"
    summary_data = {
        'analysis_date': datetime.now().isoformat(),
        'gitlab_url': gitlab_url,
        'project_paths': project_paths,
        'days_analyzed': days_back,
        'date_range': {
            'from': since_date.isoformat(),
            'to': datetime.now().isoformat()
        },
        'overall_summary': {
            'total_projects': len(all_results),
            'total_mrs_analyzed': overall_mrs,
            'total_commits': overall_commits,
            'total_pipelines': overall_pipelines,
            'total_retests': overall_retests,
            'mrs_with_retests': overall_mrs_with_retests,
            'mr_retest_rate': overall_mrs_with_retests/overall_mrs*100 if overall_mrs > 0 else 0,
            'avg_retests_per_mr': overall_retests/overall_mrs if overall_mrs > 0 else 0,
            'avg_retests_per_commit': overall_retests/overall_commits if overall_commits > 0 else 0,
        },
        'projects': all_results
    }

    with open(output_file, 'w') as f:
        json.dump(summary_data, f, indent=2)

    print(f"\n💾 Detailed results saved to: {output_file}")

    # Record overall metrics
    prom_metrics['mrs_analyzed'].labels(project='all_projects').set(overall_mrs)
    prom_metrics['retests_total'].labels(project='all_projects').set(overall_retests)

    if overall_mrs > 0:
        prom_metrics['retest_rate'].labels(project='all_projects').set(overall_mrs_with_retests/overall_mrs*100)
        prom_metrics['avg_retests_per_mr'].labels(project='all_projects').set(overall_retests/overall_mrs)

    # Push metrics to Prometheus (Pushgateway or Grafana Cloud)
    grafana_cloud_url = os.environ.get('GRAFANA_CLOUD_URL')

    if grafana_cloud_url and GRAFANA_CLOUD_AVAILABLE:
        # Push to Grafana Cloud
        print(f"\n📊 Pushing metrics to Grafana Cloud...")
        try:
            push_to_grafana_cloud(registry, job_name='gitlab-flakiness-analyzer')
            print("✅ Metrics successfully pushed to Grafana Cloud!")
        except Exception as e:
            print(f"⚠️  Failed to push metrics to Grafana Cloud: {e}")
            print("   Continuing anyway...")
    elif pushgateway_url:
        # Push to local Pushgateway
        print(f"\n📊 Pushing metrics to Prometheus Pushgateway at {pushgateway_url}...")
        try:
            push_to_gateway(pushgateway_url, job='gitlab-flakiness-analyzer', registry=registry)
            print("✅ Metrics successfully pushed to Prometheus!")
        except Exception as e:
            print(f"⚠️  Failed to push metrics to Prometheus: {e}")
            print("   Continuing anyway...")
    else:
        print("\n⚠️  No Prometheus endpoint configured (set GRAFANA_CLOUD_URL or PROMETHEUS_PUSHGATEWAY)")

    print("\n✅ Analysis complete!")


if __name__ == "__main__":
    main()
