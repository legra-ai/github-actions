"""Maintain one monitor-owned GitHub issue until verified recovery."""


def reconcile(api, repository, report):
    if report.status == 'pending':
        return
    marker = f'<!-- release-health:{report.repository} -->'
    existing = None
    # bounded: scan at most 1,000 issues in pages; exceeding the cap is an explicit failure.
    for page in range(1, 11):
        issues = api.github(f'repos/{repository}/issues?state=all&per_page=100&page={page}')
        matches = [issue for issue in issues if marker in (issue.get('body') or '')
                   and not issue.get('pull_request')
                   and issue.get('user', {}).get('login') == 'github-actions[bot]']
        if len(matches) > 1 or (matches and existing):
            raise ValueError(f'Duplicate release-health issues for {report.repository}')
        if matches:
            existing = matches[0]
        if len(issues) < 100:
            break
    else:
        raise ValueError('Issue history exceeds the 1,000-issue inspection limit')
    if existing:
        body = {'state': 'closed' if report.status == 'healthy' else 'open', 'body': report.body}
        if existing['state'] != body['state'] or existing['body'] != body['body']:
            api.github(f'repos/{repository}/issues/{existing["number"]}', method='PATCH', body=body)
    elif report.status == 'unhealthy':
        api.github(f'repos/{repository}/issues', method='POST', body={
            'title': f'Release health: {report.repository}', 'body': report.body})
