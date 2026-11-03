"""Windows launcher and browser verification against an isolated new-version database."""

import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / 'test-results'


def run(install: bool = False, batch: bool = False) -> None:
    OUTPUT.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='fleetwise-foundation-') as temporary:
        temporary_path = Path(temporary)
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        url = f'http://127.0.0.1:{port}'
        database = temporary_path / 'new.db'
        environment = os.environ | {
            'FLEET_DATABASE_URL': f'sqlite:///{database.as_posix()}',
            'FLEET_LOG_DIRECTORY': str(temporary_path / 'logs'),
            'PYTHONIOENCODING': 'utf-8',
        }
        log_path = OUTPUT / 'foundation-startup.log'
        with log_path.open('w', encoding='utf-8') as log:
            arguments = [
                'powershell.exe',
                '-NoProfile',
                '-ExecutionPolicy',
                'Bypass',
                '-File',
                str(ROOT / 'start.ps1'),
            ]
            if batch:
                arguments = ['cmd.exe', '/c', str(ROOT / 'start.bat')]
            if not install:
                arguments.append('-NoInstall')
            arguments.extend(['-Port', str(port)])
            process = subprocess.Popen(
                arguments,
                cwd=temporary,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
            )
            try:
                with httpx.Client(base_url=url, timeout=3, trust_env=False) as client:
                    deadline = time.monotonic() + (180 if install else 45)
                    while time.monotonic() < deadline:
                        if process.poll() is not None:
                            raise RuntimeError(log_path.read_text(encoding='utf-8'))
                        try:
                            response = client.get('/api/v1/context')
                            if response.status_code == 200:
                                break
                        except httpx.TransportError:
                            pass
                        time.sleep(0.2)
                    else:
                        raise RuntimeError('Windows startup timed out')
                    assert response.json()['data_revision'] == '1'
                    assert (
                        client.get(
                            '/api/v1/context', headers={'Origin': 'https://external.example'}
                        ).status_code
                        == 403
                    )
                    assert client.post('/api/v1/operations', json={}).status_code == 403
                    with sync_playwright() as playwright:
                        browser = playwright.chromium.launch(headless=True)
                        page = browser.new_page(
                            viewport={'width': 1440, 'height': 1000},
                            locale='zh-CN',
                            timezone_id='Asia/Shanghai',
                        )
                        errors = []
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        page.goto(url)
                        expect(page.get_by_role('heading', name='项目基础与公共能力')).to_be_visible()
                        expect(page.get_by_text('已连接', exact=True)).to_be_visible()
                        expect(page.get_by_test_id('revision')).to_have_text('1')
                        expect(page.get_by_text('车队长', exact=True)).to_be_visible()
                        page.screenshot(path=str(OUTPUT / 'foundation-desktop.png'), full_page=True)
                        page.get_by_role('button', name='刷新连接').click()
                        expect(page.get_by_text('已连接', exact=True)).to_be_visible()
                        # Real browser writes carry the same-origin Origin automatically.
                        denied_action = page.evaluate("""async () => {
                            const response = await fetch('/api/v1/operations', {
                                method: 'POST', headers: {'Content-Type': 'application/json'},
                                body: JSON.stringify({
                                    request_key: crypto.randomUUID(), action_code: 'CREATE_DRIVER',
                                    target_type: 'DRIVER', target_id: null, payload: {name: 'scope exercise'},
                                    expected_versions_json: {business_revision: '1'}
                                })
                            });
                            return {status: response.status, body: await response.json()};
                        }""")
                        assert denied_action['status'] == 422
                        assert denied_action['body']['code'] == 'VALIDATION_ERROR'
                        page.route('**/api/v1/context', lambda route: route.abort())
                        page.get_by_role('button', name='刷新连接').click()
                        expect(page.get_by_role('alert')).to_contain_text('无法连接本机服务')
                        page.unroute('**/api/v1/context')
                        page.get_by_role('button', name='刷新连接').click()
                        expect(page.get_by_text('已连接', exact=True)).to_be_visible()
                        page.set_viewport_size({'width': 390, 'height': 844})
                        expect(page.get_by_role('heading', name='项目基础与公共能力')).to_be_visible()
                        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                        page.screenshot(path=str(OUTPUT / 'foundation-mobile.png'), full_page=True)
                        assert errors == [], errors
                        browser.close()
                    with closing(sqlite3.connect(database)) as connection:
                        names = [
                            row[0]
                            for row in connection.execute(
                                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                            )
                        ]
                        assert len(names) == 13
                        for name in names:
                            assert not connection.execute(f'PRAGMA foreign_key_list("{name}")').fetchall()
                        assert connection.execute('SELECT count(*) FROM drivers').fetchone()[0] == 0
                        assert (
                            connection.execute('SELECT count(*) FROM business_operations').fetchone()[0] == 0
                        )
                    listening = subprocess.run(
                        [
                            'powershell.exe',
                            '-NoProfile',
                            '-Command',
                            f'Get-NetTCPConnection -State Listen -LocalPort {port} | Select-Object -ExpandProperty LocalAddress',
                        ],
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                    addresses = listening.stdout.strip().splitlines()
                    assert addresses == ['127.0.0.1'], addresses
                    report = {
                        'platform': sys.platform,
                        'launcher': arguments,
                        'url': url,
                        'listener_addresses': addresses,
                        'context_status': 200,
                        'desktop': 'passed',
                        'mobile': 'passed',
                        'browser_api': 'passed',
                        'network_failure_recovery': 'passed',
                        'page_errors': errors,
                        'schema_tables': 13,
                        'physical_foreign_keys': 0,
                        'business_data': 'empty',
                        'sqlite_version': sqlite3.sqlite_version,
                    }
            finally:
                if process.poll() is None:
                    subprocess.run(
                        ['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, check=False
                    )
                process.wait(timeout=15)
    report_name = 'foundation-batch-verification.json' if batch else 'foundation-verification.json'
    (OUTPUT / report_name).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    run(install='--install' in sys.argv, batch='--batch' in sys.argv)
