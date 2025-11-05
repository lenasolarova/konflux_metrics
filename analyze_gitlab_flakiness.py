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

            # having more than 1 page is suspicious for a 3h period
            if page > 1:
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

    def get_mr_notes(self, mr_iid):
        """Get discussion notes (comments) for an MR"""
        url = f"{self.api_base}/projects/{self.project_id}/merge_requests/{mr_iid}/notes"

        try:
            notes = self._api_request(url)
            return notes
        except Exception as e:
            print(f"    ⚠️  Error fetching notes: {e}")
            return []

    def count_retest_comments(self, mr_iid):
        """Count /retest comments in a MR

        Returns: Number of /retest comments found
        """
        try:
            notes = self.get_mr_notes(mr_iid)
            retest_count = 0

            for note in notes:
                body = note.get('body', '').strip().lower()
                # Look for /retest command (sometimes with additional text)
                if body.startswith('/retest') or '\n/retest' in body:
                    retest_count += 1

            return retest_count
        except Exception as e:
            print(f"    ⚠️  Error counting retest comments: {e}")
            return 0

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

        # Count /retest comments as a proxy for retests
        # (consistent with GitHub detection method)
        total_retests = self.count_retest_comments(mr_iid)

        return {
            'project': self.project_path,
            'mr_iid': mr_iid,
            'title': mr_info['title'],
            'merged_at': mr_info['merged_at'],
            'author': mr_info['author'],
            'total_commits': len(commits),
            'total_retests': total_retests,
            'url': f"{self.gitlab_url}/{self.project_path}/-/merge_requests/{mr_iid}"
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
    # Since we run every hour, only scrape last 3 hours (with buffer for safety)
    days_back = 7  # Analyze last 7 days to match dashboard timeframe

    # Get token from environment and strip any BOM or whitespace
    token = os.environ.get('GITLAB_TOKEN')
    if token:
        token = token.strip().lstrip('\ufeff')

    if not token:
        print("⚠️ No GITLAB_TOKEN found.")

    # date range 
    since_date = datetime.now(timezone.utc) - timedelta(days=days_back)

    # results for all projects
    all_results = {}

    for project_path in project_paths:
        print(f"\nAnalyzing {project_path} ({since_date.strftime('%Y-%m-%d')} to {datetime.now().strftime('%Y-%m-%d')})...")

        # Initialize analyzer for this project
        analyzer = GitLabFlakinessAnalyzer(gitlab_url, project_path, token)

        # only merged
        try:
            mrs = analyzer.get_merged_mrs(since_date)
        except Exception as e:
            print(f"❌ Error: {e}")
            continue

        if not mrs:
            print("No merged MRs found for this project within timeframe.")
            all_results[project_path] = {
                'mrs': [],
                'summary': {
                    'total_mrs_analyzed': 0,
                    'total_commits': 0,
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
        total_retests = sum(r['total_retests'] for r in results)
        mrs_with_retests = sum(1 for r in results if r['total_retests'] > 0)

        print(f"  {total_mrs_analyzed} MRs, {total_retests} /retest comments ({mrs_with_retests/total_mrs_analyzed*100:.1f}% rate)" if total_mrs_analyzed > 0 else "  No MRs analyzed")

        # Store results for this project
        all_results[project_path] = {
            'mrs': results,
            'summary': {
                'total_mrs_analyzed': total_mrs_analyzed,
                'total_commits': total_commits,
                'total_retests': total_retests,
                'mrs_with_retests': mrs_with_retests,
                'mr_retest_rate': mrs_with_retests/total_mrs_analyzed*100 if total_mrs_analyzed > 0 else 0,
                'avg_retests_per_mr': total_retests/total_mrs_analyzed if total_mrs_analyzed > 0 else 0,
                'avg_retests_per_commit': total_retests/total_commits if total_commits > 0 else 0,
            }
        }

    # Overall summary
    overall_mrs = sum(proj['summary']['total_mrs_analyzed'] for proj in all_results.values())
    overall_commits = sum(proj['summary']['total_commits'] for proj in all_results.values())
    overall_retests = sum(proj['summary']['total_retests'] for proj in all_results.values())
    overall_mrs_with_retests = sum(proj['summary']['mrs_with_retests'] for proj in all_results.values())

    print(f"\n📊 Total: {overall_mrs} MRs, {overall_retests} /retest comments ({overall_mrs_with_retests/overall_mrs*100:.1f}% rate)" if overall_mrs > 0 else "\n📊 No MRs analyzed")

    # Save current scrape results (all data)
    output_file = "gitlab_flakiness_current.json"
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
    print("\n✅ Analysis complete!")


if __name__ == "__main__":
    main()
