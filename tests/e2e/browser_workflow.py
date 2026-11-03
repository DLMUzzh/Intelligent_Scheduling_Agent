"""Headless UI acceptance test; launches an isolated demo database and cleans it up."""

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / 'test-results'


def run_browser(base_url: str) -> None:
    OUTPUT.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={'width': 1512, 'height': 1060}, locale='zh-CN', timezone_id='Asia/Shanghai'
        )
        page.emulate_media(reduced_motion='reduce')
        errors, server_errors = [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on(
            'response',
            lambda response: (
                server_errors.append(f'{response.status} {response.url}') if response.status >= 500 else None
            ),
        )
        page.goto(base_url)
        page.wait_for_load_state('networkidle')
        expect(page.get_by_role('heading', name='让每一班，都有序。')).to_be_visible()
        page.screenshot(path=str(OUTPUT / 'overview-desktop.png'), full_page=True)
        print('Observed navigation:', page.locator('nav a').all_text_contents())

        page.get_by_role('button', name='新建计划', exact=True).click()
        modal = page.locator('#modal')
        modal.locator('[name=title]').fill('浏览器验收计划')
        modal.locator('[name=start_date]').fill('2026-11-12')
        modal.locator('[name=end_date]').fill('2026-11-13')
        modal.get_by_role('button', name='添加日期配置').click()
        override = modal.locator('.override-block')
        override.locator('.override-date').fill('2026-11-13')
        override.get_by_role('button', name='添加类型').first.click()
        override.locator('.requirement-type').fill('Tag-B')
        override.locator('.requirement-amount').fill('60')
        modal.get_by_role('button', name='创建计划', exact=True).click()
        expect(modal).not_to_be_visible()
        expect(page.locator('main')).to_contain_text('浏览器验收计划')

        page.locator('main tr').filter(has_text='浏览器验收计划').get_by_role(
            'button', name='安排排班'
        ).click()
        expect(page.get_by_role('heading', name='排班工作台', exact=True)).to_be_visible()
        page.get_by_role('button', name='生成排班预览').click()
        expect(page.locator('.day-card')).to_have_count(2)
        expect(page.locator('.day-card').nth(1)).to_contain_text('Tag-B')
        # Reusing a wider preview must select only the dates requested this time.
        page.locator('#schedule-end').fill('2026-11-12')
        page.get_by_role('button', name='生成排班预览').click()
        expect(page.locator('#selection-count')).to_have_text('已选择 1 个待确认日期')
        page.locator('#schedule-end').fill('2026-11-13')
        page.get_by_role('button', name='生成排班预览').click()
        expect(page.locator('#selection-count')).to_have_text('已选择 2 个待确认日期')
        page.screenshot(path=str(OUTPUT / 'schedule-desktop.png'), full_page=True)

        page.locator('.day-card').first.get_by_role('button', name='编辑', exact=True).first.click()
        amount = modal.locator('.allocation-input').first
        amount.fill(str(int(amount.input_value()) - 1))
        modal.get_by_role('button', name='保存到预览').click()
        expect(modal).not_to_be_visible()
        expect(page.locator('main')).to_contain_text('版本 2')
        expect(page.locator('.day-card').first).to_contain_text('尚未分配')
        page.get_by_role('button', name='确认所选排班').click()
        expect(modal).to_contain_text('存在未分配任务')
        modal.get_by_role('button', name='确认并通知').click()
        expect(modal).not_to_be_visible()
        expect(page.locator('.day-card').first).to_contain_text('已确认')

        page.get_by_role('button', name='正式排班', exact=True).click()
        expect(page.locator('.day-card')).to_have_count(2)
        page.locator('nav a[data-page=notifications]').click()
        expect(page.get_by_role('heading', name='通知中心', exact=True)).to_be_visible()
        expect(page.locator('tbody tr')).to_have_count(8)
        expect(page.locator('tbody')).to_contain_text('发送成功')
        page.get_by_text('查看任务通知', exact=True).first.click()
        expect(page.locator('.notification-content').first).to_contain_text('采集任务通知')

        page.locator('nav a[data-page=fleet]').click()
        expect(page.get_by_role('heading', name='车队资源', exact=True)).to_be_visible()
        page.get_by_role('button', name='新增司机', exact=True).click()
        modal.locator('[name=name]').fill('浏览器测试司机')
        modal.locator('[name=efficiency_level]').select_option('HIGH')
        modal.get_by_role('button', name='保存司机', exact=True).click()
        expect(modal).not_to_be_visible()
        expect(page.locator('tbody')).to_contain_text('浏览器测试司机')
        page.get_by_role('button', name='车辆与容量').click()
        expect(page.locator('.vehicle-card')).to_have_count(4)
        page.get_by_role('button', name='编辑车辆与容量').first.click()
        modal.locator('.road-capacity').first.fill('60.001')
        modal.get_by_role('button', name='保存车辆', exact=True).click()
        expect(modal).not_to_be_visible()
        expect(page.locator('.vehicle-card').first).to_contain_text('60.001 km')
        page.get_by_role('button', name='班次配置', exact=True).click()
        expect(page.locator('tbody tr')).to_have_count(3)

        page.locator('nav a[data-page=statistics]').click()
        expect(page.get_by_role('heading', name='排班统计', exact=True)).to_be_visible()
        expect(page.locator('.metric-card').nth(1)).to_contain_text('159')
        expect(page.locator('main')).to_contain_text('浏览器测试司机')
        page.locator('nav a[data-page=agent]').click()
        expect(page.get_by_role('heading', name='为下一步智能协作，留好位置。')).to_be_visible()
        expect(page.locator('main')).to_contain_text('尚未实现')
        page.locator('nav a[data-page=audit]').click()
        expect(page.locator('tbody')).to_contain_text('确认正式排班')

        page.set_viewport_size({'width': 390, 'height': 844})
        for section in ('overview', 'plans', 'scheduling', 'fleet', 'statistics', 'notifications'):
            page.goto(f'{base_url}/#{section}')
            page.wait_for_load_state('networkidle')
            expect(page.locator('main')).not_to_contain_text('暂时无法读取数据')
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), (
                f'Horizontal page overflow: {section}'
            )
        page.goto(base_url)
        page.wait_for_load_state('networkidle')
        page.screenshot(path=str(OUTPUT / 'overview-mobile.png'), full_page=True)
        browser.close()
        assert errors == [], errors
        assert server_errors == [], server_errors
        print(
            'Browser acceptance passed: create / daily override / preview / edit / confirm / notifications / resources / statistics / mobile.'
        )


def main() -> None:
    with socket.socket() as socket_handle:
        socket_handle.bind(('127.0.0.1', 0))
        port = socket_handle.getsockname()[1]
    base_url = f'http://127.0.0.1:{port}'
    temporary = tempfile.TemporaryDirectory(prefix='fleetwise-e2e-')
    try:
        directory = temporary.name
        env = {
            **os.environ,
            'DATABASE_URL': f'sqlite:///{Path(directory).as_posix()}/test.db',
            'SEED_DEMO': 'true',
            'API_KEY': '',
        }
        OUTPUT.mkdir(exist_ok=True)
        with (OUTPUT / 'e2e-server.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen(
                [sys.executable, '-m', 'uvicorn', 'app.legacy_main:app', '--host', '127.0.0.1', '--port', str(port)],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            )
            try:
                deadline = time.monotonic() + 30
                while True:
                    if process.poll() is not None:
                        raise RuntimeError('Server stopped; inspect test-results/e2e-server.log')
                    try:
                        with urlopen(f'{base_url}/health', timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        if time.monotonic() > deadline:
                            raise RuntimeError('Server did not become ready') from None
                        time.sleep(0.2)
                run_browser(base_url)
            finally:
                if os.name == 'nt':
                    subprocess.run(
                        ['taskkill', '/PID', str(process.pid), '/T', '/F'],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                else:
                    process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    finally:
        # Windows scanners / child-process handle release can briefly retain SQLite files.
        for attempt in range(25):
            try:
                temporary.cleanup()
                break
            except PermissionError:
                if attempt == 24:
                    raise
                time.sleep(0.2)


if __name__ == '__main__':
    main()
