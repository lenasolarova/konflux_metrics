#!/usr/bin/env python3
"""Read JSON metrics files and push to Prometheus Pushgateway"""

import json
from prometheus_client import CollectorRegistry, Gauge, push_to_gateway


def push_github_metrics(pushgateway_url):
    """Read GitHub flakiness JSON and push to Pushgateway"""
    with open('github_flakiness_7days.json', 'r') as f:
        data = json.load(f)

    registry = CollectorRegistry()

    # Create metrics
    pr_retests = Gauge(
        'github_pr_retests',
        'Number of retests for individual PR',
        ['repository', 'pr_number', 'author'],
        registry=registry
    )

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

    prs_analyzed = Gauge(
        'github_flakiness_prs_analyzed_total',
        'Total number of pull requests analyzed',
        ['repository'],
        registry=registry
    )

    # Process each repository
    for repo_name, repo_data in data.get('repositories', {}).items():
        summary = repo_data.get('summary', {})

        # Set per-PR metrics
        for pr in repo_data.get('prs', []):
            pr_retests.labels(
                repository=repo_name,
                pr_number=str(pr['pr_number']),
                author=pr['author']
            ).set(pr['total_retests'])

        # Set aggregated metrics
        prs_analyzed.labels(repository=repo_name).set(summary.get('total_prs_analyzed', 0))
        retests_total.labels(repository=repo_name).set(summary.get('total_retests', 0))

        if summary.get('total_prs_analyzed', 0) > 0:
            retest_rate.labels(repository=repo_name).set(summary.get('pr_retest_rate', 0))
            avg_retests_per_pr.labels(repository=repo_name).set(summary.get('avg_retests_per_pr', 0))

    # Set overall metrics
    overall = data.get('overall_summary', {})
    prs_analyzed.labels(repository='all_repositories').set(overall.get('total_prs_analyzed', 0))
    retests_total.labels(repository='all_repositories').set(overall.get('total_retests', 0))

    if overall.get('total_prs_analyzed', 0) > 0:
        retest_rate.labels(repository='all_repositories').set(overall.get('pr_retest_rate', 0))
        avg_retests_per_pr.labels(repository='all_repositories').set(overall.get('avg_retests_per_pr', 0))

    # Push to gateway
    print("📊 Pushing GitHub metrics to Pushgateway...")
    push_to_gateway(pushgateway_url, job='github-flakiness-metrics', registry=registry)
    print("✅ GitHub metrics pushed!")


def push_gitlab_metrics(pushgateway_url):
    """Read GitLab flakiness JSON and push to Pushgateway"""
    with open('gitlab_flakiness_7days.json', 'r') as f:
        data = json.load(f)

    registry = CollectorRegistry()

    # Create metrics
    mr_retests = Gauge(
        'gitlab_mr_retests',
        'Number of retests for individual MR',
        ['project', 'mr_number', 'author'],
        registry=registry
    )

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

    mrs_analyzed = Gauge(
        'gitlab_flakiness_mrs_analyzed_total',
        'Total number of merge requests analyzed',
        ['project'],
        registry=registry
    )

    # Process each project
    for project_name, project_data in data.get('projects', {}).items():
        summary = project_data.get('summary', {})

        # Set per-MR metrics
        for mr in project_data.get('mrs', []):
            mr_retests.labels(
                project=project_name,
                mr_number=str(mr['mr_iid']),
                author=mr['author']
            ).set(mr['total_retests'])

        # Set aggregated metrics
        mrs_analyzed.labels(project=project_name).set(summary.get('total_mrs_analyzed', 0))
        retests_total.labels(project=project_name).set(summary.get('total_retests', 0))

        if summary.get('total_mrs_analyzed', 0) > 0:
            retest_rate.labels(project=project_name).set(summary.get('mr_retest_rate', 0))
            avg_retests_per_mr.labels(project=project_name).set(summary.get('avg_retests_per_mr', 0))

    # Set overall metrics
    overall = data.get('overall_summary', {})
    mrs_analyzed.labels(project='all_projects').set(overall.get('total_mrs_analyzed', 0))
    retests_total.labels(project='all_projects').set(overall.get('total_retests', 0))

    if overall.get('total_mrs_analyzed', 0) > 0:
        retest_rate.labels(project='all_projects').set(overall.get('mr_retest_rate', 0))
        avg_retests_per_mr.labels(project='all_projects').set(overall.get('avg_retests_per_mr', 0))

    # Push to gateway
    print("📊 Pushing GitLab metrics to Pushgateway...")
    push_to_gateway(pushgateway_url, job='gitlab-flakiness-metrics', registry=registry)
    print("✅ GitLab metrics pushed!")


if __name__ == '__main__':
    pushgateway_url = 'localhost:9091'

    print("🚀 Reading JSON files and pushing to Prometheus Pushgateway...")
    push_github_metrics(pushgateway_url)
    push_gitlab_metrics(pushgateway_url)
    print("✅ All metrics pushed successfully!")
