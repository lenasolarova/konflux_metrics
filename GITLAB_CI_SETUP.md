# GitLab CI/CD Setup Guide

Run the GitLab flakiness analyzer inside GitLab CI/CD on an hourly schedule.

## Why GitLab CI?

Since `gitlab.cee.redhat.com` is internal to Red Hat, we can't run the GitLab analyzer from GitHub Actions. Instead, we:
- Run it as a scheduled pipeline inside GitLab itself
- GitLab CI has access to all internal GitLab repos
- Results are pushed to your GitHub repo and Grafana Cloud

## Architecture

```
GitHub Actions (hourly)          GitLab CI (hourly)
       |                                |
       v                                v
Analyze GitHub repos            Analyze GitLab repos
       |                                |
       v                                v
Push to Grafana Cloud -----> <----- Push to Grafana Cloud
       |                                |
       v                                v
Commit to GitHub repo <------------- Push results to GitHub repo
```

Both analyzers push to the same Grafana Cloud instance and GitHub repo.

## Setup Steps

### Step 1: Create GitLab Project

You need a GitLab project to host the CI/CD pipeline. You have two options:

**Option A: Create new project on gitlab.cee.redhat.com**
1. Go to https://gitlab.cee.redhat.com
2. New Project → Create blank project
3. Name: `konflux-metrics` (or any name)
4. Visibility: Private
5. Click "Create project"

**Option B: Mirror from GitHub** (recommended)
1. Go to https://gitlab.cee.redhat.com
2. New Project → Import project → Repository by URL
3. Git repository URL: `https://github.com/lenasolarova/konflux_metrics.git`
4. Project name: `konflux-metrics`
5. Visibility: Private
6. Click "Create project"

### Step 2: Add Files to GitLab Project

If you created a new project (Option A), you need to push the analyzer files:

```bash
cd "/Users/lsolarov/Documents/KONFLUX RETEST METRIC/konflux_metrics"

# Add GitLab remote (replace with your project URL)
git remote add gitlab https://gitlab.cee.redhat.com/YOUR_USERNAME/konflux-metrics.git

# Push to GitLab
git push gitlab main
```

If you mirrored from GitHub (Option B), the files are already there. You just need to add `.gitlab-ci.yml`:

```bash
cd "/Users/lsolarov/Documents/KONFLUX RETEST METRIC/konflux_metrics"

# Commit the GitLab CI config
git add .gitlab-ci.yml
git commit -m "Add GitLab CI/CD pipeline"

# Push to both GitHub and GitLab
git push origin main
git push gitlab main  # If you set up GitLab remote
```

Or just upload `.gitlab-ci.yml` via GitLab web UI:
1. Go to your GitLab project
2. Click "+" → "New file"
3. File name: `.gitlab-ci.yml`
4. Paste the contents from your local `.gitlab-ci.yml`
5. Commit

### Step 3: Configure GitLab CI/CD Variables

Go to your GitLab project → Settings → CI/CD → Variables → Expand

Add these variables (click "Add variable" for each):

| Key | Value | Protected | Masked |
|-----|-------|-----------|--------|
| `GITLAB_TOKEN` | `Akkeo7zLyiQWkVQehtmH` | ☑ | ☑ |
| `GITHUB_TOKEN` | (from `/Users/lsolarov/Documents/SECURITY/github_access_token`) | ☑ | ☑ |
| `GRAFANA_CLOUD_URL` | `https://prometheus-prod-65-prod-eu-west-2.grafana.net/api/prom/push` | ☐ | ☐ |
| `GRAFANA_CLOUD_USER` | `2770427` | ☐ | ☑ |
| `GRAFANA_CLOUD_TOKEN` | (from `/Users/lsolarov/Documents/SECURITY/grafana_cloud_token`) | ☑ | ☑ |

**Notes:**
- Check "Protected" for tokens (only runs on protected branches)
- Check "Masked" for sensitive values (hides in logs)
- `GITLAB_TOKEN` is automatically available as `$CI_JOB_TOKEN` but we use explicit token for API access

### Step 4: Create Pipeline Schedule

Go to your GitLab project → CI/CD → Schedules → "New schedule"

Fill in:
- **Description**: `Hourly GitLab Flakiness Analysis`
- **Interval Pattern**: Custom (`0 * * * *`) - every hour at :00
  - Or use "Every hour" from dropdown
- **Cron timezone**: Your timezone (e.g., `Eastern Time (US & Canada)`)
- **Target branch**: `main`
- **Activated**: ☑ Check this box

Click "Create pipeline schedule"

### Step 5: Test the Pipeline

Run it manually first to make sure it works:

**Option A: Trigger from schedule**
1. Go to CI/CD → Schedules
2. Click "Play" button (▶️) next to your schedule

**Option B: Run pipeline directly**
1. Go to CI/CD → Pipelines
2. Click "Run pipeline"
3. Select branch: `main`
4. Click "Run pipeline"

Monitor the pipeline:
1. Click on the running pipeline
2. Click on the `analyze-gitlab-flakiness` job
3. Watch the logs - you should see:
   - "Analyzing GitLab repos for retests..."
   - Analysis output for each project
   - "Pushing results to GitHub repo..."
   - "Results pushed to GitHub!"

### Step 6: Verify Results

Check that results appear in:

1. **GitLab Artifacts**
   - Go to CI/CD → Pipelines → Click on completed pipeline
   - Click "Browse" under artifacts
   - You should see `gitlab_flakiness_7days.json`

2. **GitHub Repo**
   - Go to https://github.com/lenasolarova/konflux_metrics
   - You should see a new commit: "chore: update GitLab retest metrics [gitlab-ci]"
   - File `gitlab_flakiness_7days.json` should be updated

3. **Grafana Cloud**
   - Go to https://lsolarov.grafana.net
   - Open your dashboard
   - You should see GitLab metrics appearing

## How It Works

1. **Hourly trigger** - GitLab scheduler runs the pipeline every hour at :00
2. **Python environment** - Spins up Python 3.11 container
3. **Run analyzer** - Executes `analyze_gitlab_flakiness.py`
4. **Push to Grafana** - Sends metrics to Grafana Cloud (via environment variables)
5. **Push to GitHub** - Clones your GitHub repo, adds JSON file, commits and pushes
6. **Save artifacts** - Stores JSON in GitLab for 90 days

## Troubleshooting

### Pipeline fails with "GITLAB_TOKEN not set"

Make sure you added the CI/CD variable in Step 3. It should be:
- Key: `GITLAB_TOKEN`
- Value: Your GitLab token
- Protected: Yes
- Masked: Yes

### Can't push to GitHub

Check that:
1. `GITHUB_TOKEN` variable is set correctly in GitLab CI/CD settings
2. Token has `repo` scope (check on GitHub → Settings → Developer settings → Tokens)
3. The token hasn't expired

### Grafana Cloud push fails

Verify all three Grafana variables are set:
- `GRAFANA_CLOUD_URL`
- `GRAFANA_CLOUD_USER`
- `GRAFANA_CLOUD_TOKEN`

Test manually:
```bash
export GRAFANA_CLOUD_USER="2770427"
export GRAFANA_CLOUD_TOKEN="$(cat /Users/lsolarov/Documents/SECURITY/grafana_cloud_token)"
curl -u "$GRAFANA_CLOUD_USER:$GRAFANA_CLOUD_TOKEN" \
     -X POST "https://prometheus-prod-65-prod-eu-west-2.grafana.net/api/prom/push"
```

### Schedule not running

1. Make sure "Activated" is checked in the schedule settings
2. Check that the cron expression is correct: `0 * * * *`
3. Look at CI/CD → Schedules → Click on your schedule → "Last pipeline" should show recent runs

### GitLab API rate limits

If you hit rate limits analyzing GitLab projects:
1. Reduce the number of projects in `analyze_gitlab_flakiness.py`
2. Or increase `days_back` to run less frequently with bigger time windows
3. Or adjust the schedule to run less often (e.g., every 6 hours)

## Updating the Analyzer

When you update `analyze_gitlab_flakiness.py`:

```bash
cd "/Users/lsolarov/Documents/KONFLUX RETEST METRIC/konflux_metrics"
git add analyze_gitlab_flakiness.py
git commit -m "Update GitLab analyzer"

# Push to GitHub
git push origin main

# Push to GitLab (if you have the remote set up)
git push gitlab main
```

Or if you're using GitLab mirroring, it will auto-sync from GitHub.

## Changing the Schedule

Go to CI/CD → Schedules → Click "Edit" on your schedule

Common cron patterns:
- `0 * * * *` - Every hour at :00
- `0 */6 * * *` - Every 6 hours (00:00, 06:00, 12:00, 18:00)
- `0 0 * * *` - Daily at midnight
- `0 0 * * 1` - Weekly on Monday at midnight

## Disabling the Pipeline

To temporarily stop:
1. Go to CI/CD → Schedules
2. Click "Edit" on your schedule
3. Uncheck "Activated"
4. Save

To completely remove:
1. Go to CI/CD → Schedules
2. Click "Delete" on your schedule

## Summary

This setup runs the GitLab analyzer inside GitLab's own CI/CD infrastructure, which has access to internal GitLab repos. It:

- ✅ Runs hourly automatically
- ✅ Analyzes all 7 GitLab projects
- ✅ Pushes metrics to Grafana Cloud
- ✅ Commits results to your GitHub repo
- ✅ No local machine needed
- ✅ No VPN connection required

Combined with your GitHub Actions workflow, you now have:
- **GitHub analyzer** running in GitHub Actions (11 repos)
- **GitLab analyzer** running in GitLab CI (7 projects)
- **Both** pushing to the same Grafana Cloud dashboard
