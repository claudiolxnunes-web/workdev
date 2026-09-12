"""Single-threaded Linux PTY owner. No database credentials, tmux or API imports."""
import base64
import ctypes
import errno
import fcntl
import json
import os
from pathlib import Path
import pty
import selectors
import signal
import socket
import struct
import sys
import termios
import time


def identity(pid):
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        if fields[0] == 'Z':
            return None
        boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        return f'{boot}:{fields[19]}'
    except (OSError, IndexError):
        return None


def main():
    config = json.loads(sys.stdin.readline())
    path = Path(config['socket_path'])
    os.umask(0o077)
    # Reap orphaned descendants as well as the direct PTY child.
    if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:
        raise OSError('Cannot enable Linux subreaper')
    server = socket.socket(socket.AF_UNIX)
    server.bind(str(path))
    server.listen(8)
    server.setblocking(False)
    selector = selectors.DefaultSelector()
    selector.register(server, selectors.EVENT_READ)
    owner_pid = os.getpid()
    pid, master = pty.fork()
    if pid == 0:
        try:
            # Kernel terminates the shell if its PTY owner is killed unexpectedly.
            if ctypes.CDLL(None).prctl(1, signal.SIGKILL, 0, 0, 0) != 0 or os.getppid() != owner_pid:
                os._exit(126)
            os.chdir(config['cwd'])
            os.execvpe(config['argv'][0], config['argv'], os.environ)
        except Exception:
            os._exit(127)
    os.set_blocking(master, False)
    selector.register(master, selectors.EVENT_READ)
    state = dict(id=config['id'], supervisor_pid=os.getpid(), pid=pid,
                 process_identity=identity(pid), pty_path=None,
                 state='RUNNING', exit_code=None)
    # Child setup may not yet have replaced stdin; obtain the slave index from master.
    index = struct.unpack('I', fcntl.ioctl(master, 0x80045430, struct.pack('I', 0)))[0]
    state['pty_path'] = f'/dev/pts/{index}'
    stopping = False
    output = bytearray()
    exit_status = None
    attached = []
    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print(json.dumps(state), flush=True)
    sys.stdout.close()

    def drop_client(conn):
        if conn in attached:
            attached.remove(conn)
        try:
            selector.unregister(conn)
        except Exception:
            pass
        try:
            conn.close()
        except OSError:
            pass

    try:
        while not stopping:
            child, status = os.waitpid(pid, os.WNOHANG)
            if child:
                exit_status = os.waitstatus_to_exitcode(status)
                break
            for key, _events in selector.select(.1):
                if key.fileobj == master:
                    try:
                        chunk = os.read(master, 65536)
                        output.extend(chunk)
                        del output[:-65536]
                        event = json.dumps({'output': base64.b64encode(chunk).decode()}).encode() + b'\n'
                        for client in attached[:]:
                            try:
                                client.sendall(event)
                            except OSError:
                                drop_client(client)
                    except OSError as exc:
                        if exc.errno != errno.EIO:
                            raise
                    continue
                if key.fileobj is not server:
                    # Attached clients send nothing; readable means EOF/error.
                    conn = key.fileobj
                    try:
                        pending = conn.recv(4096)
                    except OSError:
                        pending = b''
                    if not pending:
                        drop_client(conn)
                    continue
                conn, _ = server.accept()
                keep_open = False
                try:
                    conn.settimeout(1)
                    raw = bytearray()
                    while b'\n' not in raw and len(raw) < 16384:
                        chunk = conn.recv(4096)
                        if not chunk:
                            break
                        raw.extend(chunk)
                    req = json.loads(raw)
                    if req.get('id') != config['id']:
                        response = {'error': 'Session identity mismatch'}
                    elif req.get('op') == 'close':
                        stopping = True
                        response = {**state, 'state': 'STOPPING'}
                    elif req.get('op') == 'write':
                        data = req.get('text', '').encode()
                        response = {'written': os.write(master, data)}
                    elif req.get('op') == 'resize':
                        try:
                            rows = max(5, min(int(req.get('rows')), 300))
                            cols = max(10, min(int(req.get('cols')), 500))
                        except (TypeError, ValueError):
                            response = {'error': 'Invalid terminal size'}
                        else:
                            fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))
                            response = {'rows': rows, 'cols': cols}
                    elif req.get('op') == 'health':
                        response = {**state, 'output': output.decode(errors='replace')}
                    elif req.get('op') == 'attach':
                        # Long-lived stream: ack carries the retained buffer,
                        # then every PTY chunk is pushed as a JSON line.
                        conn.sendall(json.dumps({
                            **{k: state[k] for k in ('id', 'pid', 'state')},
                            'output': base64.b64encode(bytes(output)).decode(),
                        }).encode() + b'\n')
                        conn.setblocking(False)
                        selector.register(conn, selectors.EVENT_READ)
                        attached.append(conn)
                        keep_open = True
                    else:
                        response = {'error': 'Unknown operation'}
                    if not keep_open:
                        conn.sendall(json.dumps(response).encode() + b'\n')
                except (OSError, ValueError, TypeError):
                    keep_open = False
                finally:
                    if not keep_open:
                        try:
                            conn.close()
                        except OSError:
                            pass
    finally:
        for client in attached[:]:
            drop_client(client)
        # The PTY child owns a new session/process group; never signal the API group.
        for sig, duration in ((signal.SIGTERM, .5), (signal.SIGKILL, 2)):
            try:
                os.killpg(pid, sig)
            except ProcessLookupError:
                pass
            deadline = time.monotonic() + duration
            while time.monotonic() < deadline:
                try:
                    # Descendants can call setsid(). As subreaper we adopt them
                    # after shell exit; signal only our actual children via pidfds.
                    children = Path(f'/proc/self/task/{os.getpid()}/children').read_text().split()
                    for child in children:
                        try:
                            fd = os.pidfd_open(int(child))
                            try:
                                signal.pidfd_send_signal(fd, sig)
                            finally:
                                os.close(fd)
                        except ProcessLookupError:
                            pass
                    reaped, status = os.waitpid(-1, os.WNOHANG)
                    if reaped == pid:
                        exit_status = os.waitstatus_to_exitcode(status)
                    if not reaped:
                        time.sleep(.02)
                except ChildProcessError:
                    break
        remaining = Path(f'/proc/self/task/{os.getpid()}/children').read_text().split()
        state.update(state='ERROR' if remaining else 'CLOSED', exit_code=exit_status,
                     error='Child cleanup timed out' if remaining else None)
        result = path.with_suffix('.json')
        temporary = result.with_suffix('.tmp')
        temporary.write_text(json.dumps(state))
        temporary.replace(result)
        selector.close()
        os.close(master)
        server.close()
        path.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
