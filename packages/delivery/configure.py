"""Validate local settings and stage role-scoped systemd environment files over SSH."""
import argparse
import fcntl
import json
import os
import re
import secrets
import shlex
import stat
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

FILE_KEYS = {
    'api.env': {'PUBLIC_ORIGIN', 'API_SESSION_KEY', 'API_ENABLE_OPERATOR_PROBES', 'API_OPERATOR_TOKEN'},
    'inference.env': {'INFERENCE_BASE_URL', 'INFERENCE_MODEL', 'INFERENCE_API_KEY'},
    'web.env': {'PUBLIC_HOST', 'ACME_EMAIL', 'WEB_TLS_MODE'},
}
KEYS = set().union(*FILE_KEYS.values())
MAX_INPUT = 65536


class ConfigurationError(ValueError):
    """Errors contain field names only, never configuration values."""


def clean(key, value):
    if not isinstance(value, str) or len(value.encode()) > 8192 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ConfigurationError(f'Invalid single-line value for {key}')
    return value


def parse_value(value, line):
    value = value.strip()
    if value.startswith(("'", '"')):
        quote = value[0]
        result, index = [], 1
        while index < len(value):
            char = value[index]
            if char == quote:
                rest = value[index + 1:].strip()
                if rest and not rest.startswith('#'):
                    break
                return ''.join(result)
            if char == '\\' and quote == '"' and index + 1 < len(value):
                index += 1
                following = value[index]
                if following in ('\\', '"', '$', '`'):
                    result.append(following)
                else:
                    # No interpolation or escape expansion: this is data, not shell code.
                    result.extend(('\\', following))
            else:
                result.append(char)
            index += 1
        raise ConfigurationError(f'Invalid quoted setting at line {line}')
    return re.split(r'\s+#', value, maxsplit=1)[0].rstrip()


def parse_dotenv(text, allowed=KEYS):
    if len(text.encode()) > MAX_INPUT:
        raise ConfigurationError('Environment file exceeds the input limit')
    values = {}
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        match = re.fullmatch(r'(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)', line)
        if not match:
            raise ConfigurationError(f'Expected KEY=value at line {number}')
        key, value = match.groups()
        if key in allowed:
            values[key] = clean(key, parse_value(value, number))
    return values


def load_values(env_file=None, environ=None):
    values = {}
    if env_file != '-':
        path = Path(env_file) if env_file is not None else Path('.env')
        try:
            if path.stat().st_size > MAX_INPUT:
                raise ConfigurationError('Environment file exceeds the input limit')
            values = parse_dotenv(path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            if env_file is not None:
                raise ConfigurationError('Selected environment file does not exist') from None
        except (OSError, UnicodeError):
            raise ConfigurationError('Cannot read selected environment file') from None
    source = os.environ if environ is None else environ
    values.update({key: clean(key, source[key]) for key in KEYS if key in source})
    return values


def configuration(values):
    if set(values) - KEYS:
        raise ConfigurationError('Unexpected configuration fields')
    values = {key: clean(key, value) for key, value in values.items()}
    host = values.get('PUBLIC_HOST', '').strip().lower()
    origin = values.get('PUBLIC_ORIGIN', '').strip()
    if origin:
        try:
            url = urlsplit(origin)
            valid = (url.scheme == 'https' and url.hostname and url.username is None and url.password is None
                     and not url.path and not url.query and not url.fragment and url.port in (None, 443))
        except ValueError:
            valid = False
        if not valid:
            raise ConfigurationError('PUBLIC_ORIGIN must be an exact HTTPS origin on port 443')
        derived = url.hostname.lower()
        if host and host != derived:
            raise ConfigurationError('PUBLIC_HOST must match PUBLIC_ORIGIN')
        host = derived
    if (not host or len(host) > 253 or '.' not in host
            or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in host.split('.'))):
        raise ConfigurationError('PUBLIC_HOST or PUBLIC_ORIGIN must identify a DNS hostname')
    if host.endswith(('.local', '.localhost')) or host == 'localhost' or re.fullmatch(r'[0-9.]+', host):
        raise ConfigurationError('Remote deployment requires a public DNS hostname')
    email = values.get('ACME_EMAIL', '').strip()
    tls_mode = values.get('WEB_TLS_MODE', 'acme')
    if tls_mode not in ('acme', 'internal'):
        raise ConfigurationError('WEB_TLS_MODE must be acme or internal')
    if not re.fullmatch(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}', email):
        raise ConfigurationError('ACME_EMAIL is required and must be an email address')
    base = values.get('INFERENCE_BASE_URL', 'https://api.vultrinference.com/v1').rstrip('/')
    if base != 'https://api.vultrinference.com/v1':
        raise ConfigurationError('INFERENCE_BASE_URL must use the Vultr inference endpoint')
    for key in ('INFERENCE_MODEL', 'INFERENCE_API_KEY'):
        if not values.get(key, '').strip():
            raise ConfigurationError(f'{key} is required')
    session_key = values.get('API_SESSION_KEY', '')
    if session_key and (len(session_key) < 32 or not session_key.isascii()):
        raise ConfigurationError('API_SESSION_KEY must contain at least 32 ASCII characters')
    enabled = values.get('API_ENABLE_OPERATOR_PROBES', '') or '0'
    if enabled not in ('0', '1'):
        raise ConfigurationError('API_ENABLE_OPERATOR_PROBES must be 0 or 1')
    api = {'PUBLIC_ORIGIN': 'https://' + host, 'API_ENABLE_OPERATOR_PROBES': enabled}
    if session_key:
        api['API_SESSION_KEY'] = session_key
    if enabled == '1':
        token = values.get('API_OPERATOR_TOKEN', '')
        if len(token) < 32 or not token.isascii():
            raise ConfigurationError('Enabled operator probes require a separate strong API_OPERATOR_TOKEN')
        api['API_OPERATOR_TOKEN'] = token
    return {'api.env': api, 'inference.env': {key: values[key] for key in ('INFERENCE_MODEL', 'INFERENCE_API_KEY')} |
            {'INFERENCE_BASE_URL': base},
            'web.env': {'PUBLIC_HOST': host, 'ACME_EMAIL': email, 'WEB_TLS_MODE': tls_mode}}


def render(values):
    # systemd EnvironmentFile double-quoted values; no shell evaluation or expansion.
    def quote(value):
        return '"' + ''.join('\\' + char if char in '\\"$`' else char for char in value) + '"'
    return ''.join(f'{key}={quote(clean(key, value))}\n' for key, value in sorted(values.items())).encode()


def existing_session_key(data):
    """Preserve legacy unquoted systemd values, including literal whitespace/#."""
    result = ''
    for number, line in enumerate(data.decode().splitlines(), 1):
        match = re.fullmatch(r'\s*API_SESSION_KEY\s*=(.*)', line)
        if not match:
            continue
        value = match[1].strip()
        if value.startswith(("'", '"')):
            result = parse_value(value, number)
        else:
            chars, index = [], 0
            while index < len(value):
                if value[index] == '\\':
                    index += 1
                    if index == len(value):
                        raise ConfigurationError('Existing API_SESSION_KEY needs an explicit replacement')
                chars.append(value[index])
                index += 1
            result = ''.join(chars)
    return clean('API_SESSION_KEY', result)


def read_existing(directory_fd, name):
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1:
            raise ConfigurationError('Existing service configuration must be an owned regular file')
        data = stream.read(MAX_INPUT + 1)
        if len(data) > MAX_INPUT:
            raise ConfigurationError('Existing service configuration exceeds the input limit')
        return data


def atomic_file(directory_fd, name, data):
    temporary = '.stage-' + secrets.token_hex(16)
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass


def install_files(payload, directory):
    if not isinstance(payload, dict) or set(payload) != set(FILE_KEYS):
        raise ConfigurationError('Invalid configuration payload')
    flat = {}
    for name, values in payload.items():
        if not isinstance(values, dict) or set(values) - FILE_KEYS[name]:
            raise ConfigurationError('Invalid role-scoped configuration fields')
        flat.update(values)
    files = configuration(flat)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        if os.fstat(directory_fd).st_uid != os.geteuid():
            raise ConfigurationError('Service configuration directory has the wrong owner')
        os.fchmod(directory_fd, 0o700)
        lock = os.open('.credentials.lock', os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                       0o600, dir_fd=directory_fd)
        try:
            info = os.fstat(lock)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1:
                raise ConfigurationError('Invalid credential staging lock')
            os.fchmod(lock, 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            originals = {name: read_existing(directory_fd, name) for name in FILE_KEYS}
            if 'API_SESSION_KEY' not in files['api.env']:
                old = originals['api.env']
                preserved = existing_session_key(old) if old else ''
                key = preserved or secrets.token_hex(32)
                if len(key) < 32 or not key.isascii():
                    raise ConfigurationError('Existing API_SESSION_KEY is invalid; provide an explicit replacement')
                files['api.env']['API_SESSION_KEY'] = key
            changed = []
            try:
                for name, values in files.items():
                    atomic_file(directory_fd, name, render(values))
                    changed.append(name)
                os.fsync(directory_fd)
            except BaseException:
                for name in reversed(changed):
                    if originals[name] is None:
                        os.unlink(name, dir_fd=directory_fd)
                    else:
                        atomic_file(directory_fd, name, originals[name])
                os.fsync(directory_fd)
                raise
        finally:
            os.close(lock)
    finally:
        os.close(directory_fd)


def stage(host, identity, files, known_hosts=None):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9@._-]*', host):
        raise ConfigurationError('Invalid SSH host')
    command = ['ssh', '-T', '-i', str(identity), '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes']
    if known_hosts:
        command += ['-o', 'UserKnownHostsFile=' + str(known_hosts)]
    # Only trusted program text enters argv. Settings travel exclusively through encrypted stdin.
    remote = 'python3 -c ' + shlex.quote(Path(__file__).read_text()) + ' --receive'
    command += [host, remote]
    payload = json.dumps(files)
    if len(payload.encode()) > MAX_INPUT:
        raise ConfigurationError('Configuration payload exceeds the input limit')
    try:
        connection_env = {key: os.environ[key] for key in (
            'PATH', 'HOME', 'USER', 'LOGNAME', 'LANG', 'LC_ALL', 'SSH_AUTH_SOCK', 'TMPDIR') if key in os.environ}
        result = subprocess.run(command, input=payload, text=True, capture_output=True, timeout=45,
                                env=connection_env)
    except (OSError, subprocess.TimeoutExpired):
        raise ConfigurationError('SSH credential staging could not complete') from None
    if result.returncode:
        raise ConfigurationError('Remote credential staging failed; check SSH access and remote permissions')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', help='Defaults to optional .env; use - for exported environment only')
    parser.add_argument('--host')
    parser.add_argument('--identity', type=Path)
    parser.add_argument('--known-hosts', type=Path)
    parser.add_argument('--check', action='store_true', help='Validate locally without transferring or displaying values')
    parser.add_argument('--receive', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if args.receive:
            if os.geteuid() != 0:
                raise ConfigurationError('Remote staging must run as root')
            raw = sys.stdin.buffer.read(MAX_INPUT + 1)
            if len(raw) > MAX_INPUT:
                raise ConfigurationError('Configuration payload exceeds the input limit')
            lock = os.open('/run/experiment-doctor-deploy.lock', os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                install_files(json.loads(raw), Path('/etc/experiment-doctor'))
            finally:
                os.close(lock)
        else:
            files = configuration(load_values(args.env_file))
            if not args.check:
                if not args.host or not args.identity:
                    raise ConfigurationError('--host and --identity are required for SSH staging')
                stage(args.host, args.identity, files, args.known_hosts or os.environ.get('ED_SSH_KNOWN_HOSTS'))
        print(json.dumps({'status': 'validated' if args.check else 'staged', 'files': sorted(FILE_KEYS)}))
    except (ConfigurationError, OSError, UnicodeError, ValueError, TypeError, KeyError):
        # Never echo input values, SSH output, parser snippets or tracebacks containing credentials.
        if args.receive:
            print('Remote service configuration could not be staged', file=sys.stderr)
        else:
            error = sys.exc_info()[1]
            print(str(error) if isinstance(error, ConfigurationError) else 'Invalid service configuration', file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
