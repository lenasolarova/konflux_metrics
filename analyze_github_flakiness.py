#!/usr/bin/env python3
"""Analyze historical flakiness for merged PRs in the last 30 days
Enhanced version that tracks both /retest comments and Update branch actions
"""

import json
import urllib.request
import urllib.error
from datetime import datetime, timedelta
import sys
import time
import os


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
                    'user': pr['user']['login'],
                    'base_ref': pr['base']['ref']
                })

            page += 1

            # GitHub API pagination limit
            if page > 10:
                break

        return prs

    def get_pr_comments(self, pr_number):
        """Get comments for a PR"""
        all_comments = []
        page = 1

        while True:
            url = f"{self.base_url}/issues/{pr_number}/comments?per_page=100&page={page}"

            try:
                comments = self._api_request(url)
                if not comments:
                    break

                all_comments.extend(comments)
                page += 1

                # If we got less than 100, we're on the last page
                if len(comments) < 100:
                    break

            except Exception as e:
                print(f"    ⚠️  Error fetching comments: {e}")
                break

        return all_comments

    def count_retest_comments(self, pr_number):
        """Count /retest comments in a PR

        Since GitHub/Konflux doesn't expose pipeline reruns via the API,
        we count /retest comments as a proxy for retests.

        Returns: Number of /retest comments found
        """
        try:
            comments = self.get_pr_comments(pr_number)
            retest_count = 0

            for comment in comments:
                body = comment.get('body', '').strip().lower()
                # Look for /retest command (sometimes with additional text)
                if body.startswith('/retest') or '\n/retest' in body:
                    retest_count += 1

            return retest_count
        except Exception as e:
            print(f"    ⚠️  Error fetching comments: {e}")
            return 0

    def get_pr_commits(self, pr_number):
        """Get commits for a PR"""
        url = f"{self.base_url}/pulls/{pr_number}/commits"
        commits = self._api_request(url)
        return commits

    def count_update_branch_commits(self, pr_number, base_ref):
        """Count merge commits that likely came from 'Update branch' button

        These are merge commits that merge the base branch into the PR branch.

        Returns: Number of update branch commits found
        """
        try:
            commits = self.get_pr_commits(pr_number)
            update_branch_count = 0

            for commit in commits:
                # Check if this is a merge commit (has 2 parents)
                if len(commit.get('parents', [])) == 2:
                    commit_msg = commit['commit']['message'].lower()
                    # Check if it's merging the base branch
                    if f"merge branch '{base_ref}'" in commit_msg or \
                       f'merge branch "{base_ref}"' in commit_msg or \
                       f"merge remote-tracking branch" in commit_msg:
                        update_branch_count += 1

            return update_branch_count
        except Exception as e:
            print(f"    ⚠️  Error fetching commits: {e}")
            return 0

    def analyze_pr(self, pr_info):
        """Analyze flakiness for a single PR"""
        pr_number = pr_info['number']
        base_ref = pr_info['base_ref']

        try:
            commits = self.get_pr_commits(pr_number)
        except Exception as e:
            print(f"    ⚠️  Error fetching commits: {e}")
            return None

        # Count /retest comments
        retest_comments = self.count_retest_comments(pr_number)

        # Count "Update branch" merge commits
        update_branch_count = self.count_update_branch_commits(pr_number, base_ref)

        # Total retests = /retest comments + update branch actions
        total_retests = retest_comments + update_branch_count

        return {
            'repository': self.repo,
            'pr_number': pr_number,
            'title': pr_info['title'],
            'merged_at': pr_info['merged_at'],
            'user': pr_info['user'],
            'total_commits': len(commits),
            'retest_comments': retest_comments,
            'update_branch_count': update_branch_count,
            'total_retests': total_retests,
            'url': f"https://github.com/{self.repo}/pull/{pr_number}"
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
    # Analyze last 1 day for incremental updates (24h window to catch overlaps)
    # Can be overridden with DAYS_BACK environment variable for backfilling
    days_back = int(os.environ.get('DAYS_BACK', '1'))

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
                    'total_retests': 0,
                    'retest_comments': 0,
                    'update_branch_actions': 0,
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
        total_retests = sum(r['total_retests'] for r in results)
        total_retest_comments = sum(r['retest_comments'] for r in results)
        total_update_branch = sum(r['update_branch_count'] for r in results)
        prs_with_retests = sum(1 for r in results if r['total_retests'] > 0)

        print(f"  {total_prs_analyzed} PRs, {total_retests} retests " +
              f"({total_retest_comments} /retest, {total_update_branch} update branch) " +
              f"({prs_with_retests/total_prs_analyzed*100:.1f}% rate)" if total_prs_analyzed > 0 else "  No PRs analyzed")

        # Store results for this repo
        all_results[repo] = {
            'prs': results,
            'summary': {
                'total_prs_analyzed': total_prs_analyzed,
                'total_commits': total_commits,
                'total_retests': total_retests,
                'retest_comments': total_retest_comments,
                'update_branch_actions': total_update_branch,
                'prs_with_retests': prs_with_retests,
                'pr_retest_rate': prs_with_retests/total_prs_analyzed*100 if total_prs_analyzed > 0 else 0,
                'avg_retests_per_pr': total_retests/total_prs_analyzed if total_prs_analyzed > 0 else 0,
                'avg_retests_per_commit': total_retests/total_commits if total_commits > 0 else 0,
            }
        }

    # Overall summary
    overall_prs = sum(repo['summary']['total_prs_analyzed'] for repo in all_results.values())
    overall_commits = sum(repo['summary']['total_commits'] for repo in all_results.values())
    overall_retests = sum(repo['summary']['total_retests'] for repo in all_results.values())
    overall_retest_comments = sum(repo['summary']['retest_comments'] for repo in all_results.values())
    overall_update_branch = sum(repo['summary']['update_branch_actions'] for repo in all_results.values())
    overall_prs_with_retests = sum(repo['summary']['prs_with_retests'] for repo in all_results.values())

    print(f"\n📊 Total: {overall_prs} PRs, {overall_retests} retests " +
          f"({overall_retest_comments} /retest, {overall_update_branch} update branch) " +
          f"({overall_prs_with_retests/overall_prs*100:.1f}% rate)" if overall_prs > 0 else "\n📊 No PRs analyzed")

    # Save current scrape results (all data)
    output_file = "github_flakiness_current.json"
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
            'total_retests': overall_retests,
            'retest_comments': overall_retest_comments,
            'update_branch_actions': overall_update_branch,
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
    print("\n✅ Analysis complete!")


if __name__ == "__main__":
    main()
