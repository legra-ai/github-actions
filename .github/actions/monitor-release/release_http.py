"""Bounded public downloads and authenticated GitHub API requests."""

from contextlib import contextmanager
import base64
import hashlib
import json
from pathlib import Path
import tempfile
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class API:
    def __init__(self, token):
        self.token = token

    def github(self, path, method='GET', body=None):
        if path.startswith('/') or '://' in path:
            raise ValueError('Expected a relative GitHub API path')
        headers = {'Accept': 'application/vnd.github+json',
                   'Authorization': f'Bearer {self.token}', 'User-Agent': 'legra-release-health'}
        data = None if body is None else json.dumps(body).encode()
        return self.request_json(Request(f'https://api.github.com/{path}', data=data,
                                         headers=headers, method=method))

    def json(self, url):
        return self.request_json(Request(url, headers={'User-Agent': 'legra-release-health'}))

    def request_json(self, request):
        try:
            with urlopen(request, timeout=30) as response:
                # bounded: JSON metadata is capped at 4 MiB; never hydrate registry histories.
                data = response.read(4 * 1024 * 1024 + 1)
            if len(data) > 4 * 1024 * 1024:
                raise ValueError('API metadata exceeds 4 MiB')
            return json.loads(data)
        except HTTPError as error:
            if error.code == 404:
                error.close()
                return None
            error.close()
            raise RuntimeError(f'HTTP {error.code}: {request.full_url}') from None

    def text(self, path):
        data = self.github(path)
        if data is None:
            raise ValueError(f'Missing repository file: {path}')
        return base64.b64decode(data['content'], validate=False).decode()

    @contextmanager
    def download(self, url):
        if not url.startswith('https://'):
            raise ValueError('Artifact downloads require HTTPS')
        with tempfile.TemporaryDirectory(prefix='release-health-') as directory:
            path = Path(directory) / 'artifact'
            digest = hashlib.sha256()
            size = 0
            request = Request(url, headers={'User-Agent': 'legra-release-health'})
            try:
                source = urlopen(request, timeout=30)
            except HTTPError as error:
                error.close()
                raise RuntimeError(f'HTTP {error.code}: {url}') from None
            with source, path.open('wb') as destination:
                while chunk := source.read(64 * 1024):
                    size += len(chunk)
                    if size > 512 * 1024 * 1024:
                        raise ValueError('Artifact exceeds 512 MiB')
                    destination.write(chunk)
                    digest.update(chunk)
            if size == 0:
                raise ValueError('Empty artifact download')
            yield path, digest.hexdigest()
