#!/usr/bin/env python3
"""
Append incremental scrape data to historical files.

This script:
1. Reads the 24h increment files (github_flakiness_current.json, gitlab_flakiness_current.json)
2. Merges with existing 90-day historical files
3. Deduplicates entries (by PR#/MR# + repo/project)
4. Trims data older than 90 days
5. Saves to historical files for Grafana
"""

import json
import jq
from datetime import datetime, timedelta, timezone
from pathlib import Path


def load_json(filepath):
    """Load JSON file, return empty structure if doesn't exist"""
    path = Path(filepath)
    if not path.exists():
        return None
    with open(path, 'r') as f:
        return json.load(f)


def save_json(filepath, data):
    """Save JSON file with pretty formatting"""
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)


def get_platform_config(platform):
    """Get platform-specific configuration"""
    configs = {
        'github': {
            'label': 'GitHub',
            'container_key': 'repositories',
            'items_key': 'prs',
            'id_key': 'pr_number',
            'item_name': 'PR',
            'item_name_plural': 'PRs',
            'extra_metrics': True
        },
        'gitlab': {
            'label': 'GitLab',
            'container_key': 'projects',
            'items_key': 'mrs',
            'id_key': 'mr_iid',
            'item_name': 'MR',
            'item_name_plural': 'MRs',
            'extra_metrics': False
        }
    }
    return configs[platform]


def initialize_historical(container_key, days_to_keep):
    """Create new historical data structure"""
    return {
        'created_at': datetime.now(timezone.utc).isoformat(),
        'days_analyzed': days_to_keep,
        container_key: {}
    }


def merge_and_filter_items(existing_items, new_items, id_key, cutoff_iso):
    """Merge new items with existing, deduplicate, and filter by date"""
    #create lookup dict by ID
    existing_dict = {item[id_key]: item for item in existing_items}

    #merge/update items
    for new_item in new_items:
        existing_dict[new_item[id_key]] = new_item

    #convert to list
    all_items = list(existing_dict.values())

    #filter old items using jq
    filtered_items = jq.compile(f'''
        map(select(.merged_at >= "{cutoff_iso}"))
    ''').input(all_items).first()

    #sort by merged_at descending
    filtered_items.sort(key=lambda x: x['merged_at'], reverse=True)

    return filtered_items


def calculate_summary(all_items, cfg):
    """Calculate summary statistics"""
    total_items = len(all_items)
    total_retests = sum(item.get('total_retests', 0) for item in all_items)
    items_with_retests = sum(1 for item in all_items if item.get('total_retests', 0) > 0)

    summary = {
        f"total_{cfg['items_key'].rstrip('s')}s": total_items,
        'total_retests': total_retests,
        f"{cfg['items_key'].rstrip('s')}s_with_retests": items_with_retests,
        'retest_rate': (items_with_retests / total_items * 100) if total_items > 0 else 0
    }

    #add github-specific metrics
    if cfg['extra_metrics']:
        summary['retest_comments'] = sum(item.get('retest_comments', 0) for item in all_items)
        summary['update_branch_actions'] = sum(item.get('update_branch_count', 0) for item in all_items)

    return summary


def print_summary(total_items, cfg, summary):
    """Print formatted summary"""
    if cfg['extra_metrics']:
        print(f"  📈 Total: {total_items} {cfg['item_name_plural']}, {summary['total_retests']} retests "
              f"({summary['retest_comments']} /retest, {summary['update_branch_actions']} update branch)")
    else:
        print(f"  📈 Total: {total_items} {cfg['item_name_plural']}, {summary['total_retests']} retests")


def merge_data(increment_file, historical_file, output_file, platform='github', days_to_keep=90):
    """
    Generic merge function for both GitHub and GitLab data.

    Args:
        increment_file: Path to 24h increment JSON
        historical_file: Path to existing 90-day historical JSON
        output_file: Path to save merged historical JSON
        platform: 'github' or 'gitlab'
        days_to_keep: Number of days to retain (default 90)
    """
    #platform-specific config
    config = {
        'github': {
            'label': 'GitHub',
            'container_key': 'repositories',
            'items_key': 'prs',
            'id_key': 'pr_number',
            'item_name': 'PR',
            'item_name_plural': 'PRs',
            'extra_metrics': True
        },
        'gitlab': {
            'label': 'GitLab',
            'container_key': 'projects',
            'items_key': 'mrs',
            'id_key': 'mr_iid',
            'item_name': 'MR',
            'item_name_plural': 'MRs',
            'extra_metrics': False
        }
    }

    cfg = config[platform]
    print(f"{'📊' if platform == 'github' else '\n📊'} Merging {cfg['label']} data...")

    #load small and big data
    increment = load_json(increment_file)
    historical = load_json(historical_file)

    if not increment:
        print(f"  ⚠️  No increment data found at {increment_file}")
        return

    #initialize historical if doesn't exist
    if not historical:
        print(f"  📝 Creating new historical file")
        historical = {
            'created_at': datetime.now(timezone.utc).isoformat(),
            'days_analyzed': days_to_keep,
            cfg['container_key']: {}
        }

    #calculate cutoff date
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_to_keep)
    cutoff_iso = cutoff_date.isoformat()

    #merge places (repos/projects)
    for name, data in increment.get(cfg['container_key'], {}).items():
        if name not in historical[cfg['container_key']]:
            historical[cfg['container_key']][name] = {cfg['items_key']: []}

        #get existing and new items
        existing_items = historical[cfg['container_key']][name].get(cfg['items_key'], [])
        new_items = data.get(cfg['items_key'], [])

        #create lookup dict by ID
        existing_dict = {item[cfg['id_key']]: item for item in existing_items}

        #merge/update items
        for new_item in new_items:
            item_id = new_item[cfg['id_key']]
            existing_dict[item_id] = new_item

        #convert to list and filter by date
        all_items = list(existing_dict.values())

        #filter old items using jq
        filtered_items = jq.compile(f'''
            map(select(.merged_at >= "{cutoff_iso}"))
        ''').input(all_items).first()

        #sort by merged_at descending
        filtered_items.sort(key=lambda x: x['merged_at'], reverse=True)

        historical[cfg['container_key']][name][cfg['items_key']] = filtered_items

        print(f"  ✓ {name}: {len(new_items)} new, {len(filtered_items)} total (after trim)")

    #update metadata
    historical['last_updated'] = datetime.now(timezone.utc).isoformat()
    historical['cutoff_date'] = cutoff_iso

    #calculate overall summary
    all_items = []
    for container_data in historical[cfg['container_key']].values():
        all_items.extend(container_data.get(cfg['items_key'], []))

    total_items = len(all_items)
    total_retests = sum(item.get('total_retests', 0) for item in all_items)
    items_with_retests = sum(1 for item in all_items if item.get('total_retests', 0) > 0)

    #build summary
    summary = {
        f"total_{cfg['items_key'].rstrip('s')}s": total_items,
        'total_retests': total_retests,
        f"{cfg['items_key'].rstrip('s')}s_with_retests": items_with_retests,
        'retest_rate': (items_with_retests / total_items * 100) if total_items > 0 else 0
    }

    #add github-specific metrics
    if cfg['extra_metrics']:
        total_retest_comments = sum(item.get('retest_comments', 0) for item in all_items)
        total_update_branch = sum(item.get('update_branch_count', 0) for item in all_items)
        summary['retest_comments'] = total_retest_comments
        summary['update_branch_actions'] = total_update_branch

    historical['summary'] = summary

    #save
    save_json(output_file, historical)
    print(f"  💾 Saved to {output_file}")

    #print summary
    if cfg['extra_metrics']:
        print(f"  📈 Total: {total_items} {cfg['item_name_plural']}, {total_retests} retests "
              f"({summary['retest_comments']} /retest, {summary['update_branch_actions']} update branch)")
    else:
        print(f"  📈 Total: {total_items} {cfg['item_name_plural']}, {total_retests} retests")


def main():
    """Main execution"""
    print("=" * 80)
    print("Historical Data Append Tool")
    print("=" * 80)

    #github
    merge_data(
        increment_file='github_flakiness_current.json',
        historical_file='github_flakiness_historical.json',
        output_file='github_flakiness_historical.json',
        platform='github',
        days_to_keep=90
    )

    #gitlab
    merge_data(
        increment_file='gitlab_flakiness_current.json',
        historical_file='gitlab_flakiness_historical.json',
        output_file='gitlab_flakiness_historical.json',
        platform='gitlab',
        days_to_keep=90
    )

    print("\n✅ Historical data updated successfully!")
    print("=" * 80)


if __name__ == "__main__":
    main()
