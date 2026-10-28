"""Bounded local transport for a host that produces model response files.

The transport does not authenticate the writer or imply an external model API
was used. A responder must publish complete response JSON atomically.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import time
import uuid

from .reasoning_frame import canonical, digest


ROOT = Path(__file__).resolve().parents[1]
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 600


def new_directory(path):
    path = Path(path).resolve()
    allowed = (ROOT / 'data/private/reasoning_sessions').resolve()
    if not path.is_relative_to(allowed) or path == allowed:
        raise ValueError('Output must be a new child of data/private/reasoning_sessions')
    path.mkdir(parents=True, exist_ok=False)
    return path


def atomic_json(path, value):
    """Publish complete JSON with an atomic, no-replace hard link."""
    path = Path(path)
    raw = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)  # Atomic publication; existing targets fail.
    finally:
        temporary.unlink(missing_ok=True)


def file_sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class FileModelBridge:
    def __init__(self, exchange_dir, *, timeout_seconds=DEFAULT_TIMEOUT_SECONDS, poll_interval=0.2,
                 max_response_bytes=MAX_RESPONSE_BYTES, on_request=None,
                 clock=time.monotonic, sleep=time.sleep):
        for name, value in [('timeout_seconds', timeout_seconds), ('poll_interval', poll_interval)]:
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError(name + ' must be a positive finite number')
        if type(max_response_bytes) is not int or max_response_bytes < 1:
            raise ValueError('max_response_bytes must be a positive integer')
        self.directory = new_directory(exchange_dir)
        (self.directory / 'requests').mkdir()
        (self.directory / 'responses').mkdir()
        self.timeout_seconds = timeout_seconds
        self.poll_interval = poll_interval
        self.max_response_bytes = max_response_bytes
        self.on_request = on_request
        self.clock, self.sleep = clock, sleep
        self.sequence = 0

    def __call__(self, request):
        if not isinstance(request, dict) or set(request) != {'messages', 'tools', 'response_schema'}:
            raise ValueError('Only runner messages, tools and response_schema may enter the bridge')
        canonical(request)  # Refuse nonfinite/non-JSON requests before publishing.
        self.sequence += 1
        name = f'{self.sequence:02d}.json'
        request_id = 'request_' + digest({'sequence': self.sequence, 'request': request})
        request_path = self.directory / 'requests' / name
        response_path = self.directory / 'responses' / name
        if response_path.exists():
            raise FileExistsError('Response already exists before request publication')
        atomic_json(request_path, {'request_id': request_id, 'request': request})
        if self.on_request:
            self.on_request({'event': 'model_request_ready', 'sequence': self.sequence,
                             'request_id': request_id, 'request_path': str(request_path),
                             'response_path': str(response_path), 'atomic_response_required': True})
        deadline = self.clock() + self.timeout_seconds
        while not response_path.exists():
            remaining = deadline - self.clock()
            if remaining <= 0:
                raise TimeoutError(f'No response for request {self.sequence} within {self.timeout_seconds:g} seconds')
            self.sleep(min(self.poll_interval, remaining))
        with response_path.open('rb') as stream:
            raw = stream.read(self.max_response_bytes + 1)
        if len(raw) > self.max_response_bytes:
            raise ValueError('Response exceeds maximum byte size')
        def reject_constant(value):
            raise ValueError('Nonfinite JSON response: ' + value)
        response = json.loads(raw.decode('utf-8'), parse_constant=reject_constant)
        canonical(response)  # Also rejects overflowed numeric literals such as 1e999.
        if not isinstance(response, dict) or set(response) != {'request_id', 'response'}:
            raise ValueError('Expected request_id and response envelope')
        if response['request_id'] != request_id:
            raise ValueError('Response request_id does not match the published request')
        payload = response['response']
        if not isinstance(payload, dict) or set(payload) not in ({'answer'}, {'tool_requests'}):
            raise ValueError('Expected exactly one answer or tool_requests response')
        return payload


def file_generate(exchange_dir, **kwargs):
    return FileModelBridge(exchange_dir, **kwargs)
