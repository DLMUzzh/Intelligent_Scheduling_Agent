"""Real Windows launcher and Chromium workflows. All business data uses an isolated database."""

import sqlite3
import sys
from contextlib import closing
from datetime import date, timedelta

from playwright.sync_api import expect, sync_playwright

from tests.e2e.foundation_browser import OUTPUT, run


def review_and_execute(page):
    review = page.get_by_role('dialog', name='操作预览与确认', exact=True)
    expect(review.get_by_text('待确认', exact=True)).to_be_visible()
    review.get_by_role('button', name='保存并生效', exact=True).click()
    expect(review.get_by_text('已生效', exact=True)).to_be_visible()
    review.get_by_role('button', name='关闭', exact=True).click()
    expect(review).not_to_be_visible()


def new_category(page, name, mode='TAG'):
    page.get_by_role('button', name='新增类别', exact=True).click()
    editor = page.get_by_role('dialog', name='新增类别', exact=True)
    editor.get_by_label('类别模式', exact=True).select_option(mode)
    editor.get_by_label('类别名称', exact=True).fill(name)
    editor.get_by_role('button', name='查看变更', exact=True).click()
    review_and_execute(page)


def exercise(url, database):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={'width': 1600, 'height': 1050}, locale='zh-CN', timezone_id='Asia/Shanghai'
        )
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(url + '/#/categories')
        page.wait_for_load_state('networkidle')
        expect(page.get_by_role('heading', name='采集类别', exact=True)).to_be_visible()
        page.screenshot(path=str(OUTPUT / 'base-data-initial.png'), full_page=True)
        # Inspect actual controls before exercising the rendered page.
        assert page.get_by_label('采集模式', exact=True).count() == 1
        assert page.get_by_role('button', name='新增类别', exact=True).is_enabled()
        if '--inspect' in sys.argv:
            browser.close()
            return {'inspection': 'passed', 'page_errors': errors}
        new_category(page, '联调类别')
        new_category(page, '联调类别', 'ROAD')
        row = page.get_by_role('row').filter(has_text='联调类别').filter(has_text='Tag')
        row.get_by_role('button', name='更名', exact=True).click()
        editor = page.get_by_role('dialog', name='类别更名', exact=True)
        editor.get_by_label('类别名称', exact=True).fill('联调新类别')
        editor.get_by_role('button', name='查看变更', exact=True).click()
        review_and_execute(page)
        expect(page.get_by_role('row').filter(has_text='联调新类别')).to_be_visible()
        page.get_by_role('row').filter(has_text='联调类别').filter(has_text='道路').get_by_role(
            'button', name='删除', exact=True
        ).click()
        review_and_execute(page)

        page.get_by_role('link', name='车队资源', exact=True).click()
        expect(page.get_by_role('heading', name='车队资源', exact=True)).to_be_visible()
        page.get_by_role('button', name='新增司机', exact=True).click()
        editor = page.get_by_role('dialog', name='新增司机', exact=True)
        editor.get_by_label('司机姓名', exact=True).fill('联调司机')
        editor.get_by_label('联系方式', exact=True).fill('13800000000')
        editor.get_by_label('效率等级', exact=True).select_option('HIGH')
        editor.get_by_label('中班资格', exact=True).uncheck()
        editor.get_by_role('button', name='查看变更', exact=True).click()
        review_and_execute(page)
        row = page.get_by_role('row').filter(has_text='联调司机')
        expect(row).to_contain_text('高效率')
        expect(row).to_contain_text('早班 · 晚班')
        row.get_by_role('button', name='详情', exact=True).click()
        detail = page.get_by_role('dialog', name='司机详情', exact=True)
        expect(detail).to_contain_text('13800000000')
        detail.get_by_role('button', name='关闭', exact=True).click()
        row.get_by_role('button', name='停用', exact=True).click()
        review_and_execute(page)
        expect(row).to_contain_text('已停用')
        row.get_by_role('button', name='启用', exact=True).click()
        review_and_execute(page)

        page.get_by_role('button', name='车辆资料', exact=True).click()
        page.get_by_role('button', name='新增车辆', exact=True).click()
        editor = page.get_by_role('dialog', name='新增车辆', exact=True)
        editor.get_by_label('车牌号', exact=True).fill('辽B联调01')
        editor.get_by_label('车辆名称', exact=True).fill('测试采集车')
        for shift, tag, road in [
            ('早班', '9007199254740993', '1.001'),
            ('中班', '20', '2.125'),
            ('晚班', '0', '0'),
        ]:
            editor.get_by_label(f'{shift} Tag 容量', exact=True).fill(tag)
            editor.get_by_label(f'{shift}道路容量', exact=True).fill(road)
        editor.get_by_label('车辆备注', exact=True).fill('六项容量联调')
        editor.get_by_role('button', name='查看变更', exact=True).click()
        review_and_execute(page)
        row = page.get_by_role('row').filter(has_text='辽B联调01')
        expect(row).to_contain_text('9007199254740993 / 20 / 0')
        expect(row).to_contain_text('1.001 / 2.125 / 0')
        page.screenshot(path=str(OUTPUT / 'base-data-vehicles.png'), full_page=True)
        row.get_by_role('button', name='详情', exact=True).click()
        detail = page.get_by_role('dialog', name='车辆详情', exact=True)
        expect(detail).to_contain_text('六项容量联调')
        detail.get_by_role('button', name='关闭', exact=True).click()
        row.get_by_role('button', name='编辑', exact=True).click()
        editor = page.get_by_role('dialog', name='编辑车辆', exact=True)
        editor.get_by_label('中班 Tag 容量', exact=True).fill('30')
        editor.get_by_label('中班道路容量', exact=True).fill('3.333')
        editor.get_by_role('button', name='查看变更', exact=True).click()
        review_and_execute(page)
        expect(row).to_contain_text('9007199254740993 / 30 / 0')
        expect(row).to_contain_text('1.001 / 3.333 / 0')
        page.get_by_role('button', name='新增车辆', exact=True).click()
        editor = page.get_by_role('dialog', name='新增车辆', exact=True)
        editor.get_by_label('车牌号', exact=True).fill('辽b 联调01')
        editor.get_by_role('button', name='查看变更', exact=True).click()
        review = page.get_by_role('dialog', name='操作预览与确认', exact=True)
        expect(review).to_contain_text('车牌号已存在')
        review.get_by_role('button', name='关闭', exact=True).click()
        editor.get_by_label('车牌号', exact=True).fill('临时车辆')
        editor.get_by_role('button', name='查看变更', exact=True).click()
        review_and_execute(page)
        page.get_by_role('row').filter(has_text='临时车辆').get_by_role(
            'button', name='删除', exact=True
        ).click()
        review_and_execute(page)
        expect(page.get_by_role('row').filter(has_text='临时车辆')).to_have_count(0)

        # Leave and maintenance use actual resource versions and the same confirmation protocol.
        today = page.request.get(url + '/api/v1/context').json()['data']['business_date']
        start = (date.fromisoformat(today) + timedelta(days=1)).isoformat()
        end = (date.fromisoformat(today) + timedelta(days=3)).isoformat()
        for resource_kind in ('VEHICLE', 'DRIVER'):
            if resource_kind == 'DRIVER':
                page.get_by_role('button', name='司机资料', exact=True).click()
            row = page.get_by_role('row').filter(
                has_text='辽B联调01' if resource_kind == 'VEHICLE' else '联调司机'
            )
            row.get_by_role('link', name='维修' if resource_kind == 'VEHICLE' else '请假', exact=True).click()
            page.get_by_role('button', name='新增不可用记录', exact=True).click()
            editor = page.get_by_role('dialog', name='新增不可用记录', exact=True)
            editor.get_by_label('不可用开始日期', exact=True).fill(start)
            editor.get_by_label('不可用结束日期', exact=True).fill(end)
            editor.get_by_label('不可用原因', exact=True).fill(
                '保养' if resource_kind == 'VEHICLE' else '事假'
            )
            editor.get_by_role('button', name='查看变更', exact=True).click()
            review_and_execute(page)
            row = page.get_by_role('row').filter(has_text=start).filter(has_text=end)
            row.get_by_role('button', name='编辑', exact=True).click()
            editor = page.get_by_role('dialog', name='编辑不可用记录', exact=True)
            editor.get_by_label('不可用结束日期', exact=True).fill(start)
            editor.get_by_label('不可用原因', exact=True).fill('修改后原因')
            editor.get_by_role('button', name='查看变更', exact=True).click()
            review_and_execute(page)
            row = page.get_by_role('row').filter(has_text='修改后原因')
            row.get_by_role('button', name='取消记录', exact=True).click()
            review_and_execute(page)
            expect(page.get_by_text('暂无符合条件的请假或维修记录', exact=True)).to_be_visible()
            page.get_by_role('link', name='车队资源', exact=True).click()
            expect(page.get_by_role('button', name='新增司机', exact=True)).to_be_visible()

        # A different browser tab changes the global revision after the first tab prepared an edit.
        row = page.get_by_role('row').filter(has_text='联调司机')
        row.get_by_role('button', name='编辑', exact=True).click()
        editor = page.get_by_role('dialog', name='编辑司机', exact=True)
        editor.get_by_label('联系方式', exact=True).fill('13900000000')
        editor.get_by_role('button', name='查看变更', exact=True).click()
        review = page.get_by_role('dialog', name='操作预览与确认', exact=True)
        expect(review.get_by_text('待确认', exact=True)).to_be_visible()
        other = browser.new_page()
        other.goto(url + '/#/categories')
        other.wait_for_load_state('networkidle')
        new_category(other, '并发类别')
        other.close()
        review.get_by_role('button', name='保存并生效', exact=True).click()
        expect(review.get_by_text('未生效', exact=True)).to_be_visible()
        expect(review).to_contain_text('数据已变化')
        review.get_by_role('button', name='关闭', exact=True).click()
        expect(editor.get_by_label('联系方式', exact=True)).to_have_value('13900000000')
        editor.get_by_role('button', name='刷新版本并保留输入', exact=True).click()
        expect(editor).to_contain_text('已刷新当前版本')
        editor.get_by_role('button', name='查看变更', exact=True).click()
        review_and_execute(page)

        # The database commits but the execution response is lost. Only a GET is used to recover.
        row.get_by_role('button', name='编辑', exact=True).click()
        editor = page.get_by_role('dialog', name='编辑司机', exact=True)
        editor.get_by_label('联系方式', exact=True).fill('13700000000')
        editor.get_by_role('button', name='查看变更', exact=True).click()
        lost_responses = []

        def commit_then_drop(route):
            lost_responses.append(route.request.url)
            route.fetch()
            route.abort('failed')

        page.route('**/api/v1/operations/*/executions', commit_then_drop)
        review.get_by_role('button', name='保存并生效', exact=True).click()
        expect(review.get_by_role('button', name='核实结果', exact=True)).to_be_visible()
        expect(review.get_by_role('button', name='核实结果', exact=True)).to_be_enabled()
        page.unroute('**/api/v1/operations/*/executions')
        review.get_by_role('button', name='核实结果', exact=True).click()
        expect(review.get_by_text('已生效', exact=True)).to_be_visible()
        review.get_by_role('button', name='关闭', exact=True).click()
        assert len(lost_responses) == 1
        expect(row).to_contain_text('13700000000')
        page.get_by_role('button', name='新增司机', exact=True).click()
        editor = page.get_by_role('dialog', name='新增司机', exact=True)
        editor.get_by_label('司机姓名', exact=True).fill('临时司机')
        editor.get_by_role('button', name='查看变更', exact=True).click()
        review_and_execute(page)
        page.get_by_role('row').filter(has_text='临时司机').get_by_role(
            'button', name='删除', exact=True
        ).click()
        review_and_execute(page)
        expect(page.get_by_role('row').filter(has_text='临时司机')).to_have_count(0)

        # A lost preparation survives a browser reload with the original UUID and frozen input.
        page.get_by_role('link', name='采集类别', exact=True).click()
        page.get_by_role('button', name='新增类别', exact=True).click()
        editor = page.get_by_role('dialog', name='新增类别', exact=True)
        editor.get_by_label('类别名称', exact=True).fill('恢复类别')
        page.route('**/api/v1/operations', commit_then_drop)
        editor.get_by_role('button', name='查看变更', exact=True).click()
        expect(review.get_by_role('button', name='核实结果', exact=True)).to_be_visible()
        expect(review.get_by_role('button', name='核实结果', exact=True)).to_be_enabled()
        page.unroute('**/api/v1/operations')
        page.reload()
        expect(review.get_by_text('待确认', exact=True)).to_be_visible()
        expect(review).to_contain_text('恢复类别')
        review_and_execute(page)

        # Populate a second page through the actual business protocol, then exercise both pagers.
        added_ids = page.evaluate("""async () => {
            const call = async (path, body) => {
                const response = await fetch('/api/v1' + path, body === undefined ? {} : {
                    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
                });
                const value = await response.json();
                if (!response.ok) throw new Error(value.code);
                return value;
            };
            let revision = (await call('/context')).data_revision;
            const ids = [];
            for (let index = 1; index <= 20; index++) {
                const prepared = await call('/operations', {
                    request_key: crypto.randomUUID(), action_code: 'CREATE_DRIVER', target_type: 'DRIVER',
                    target_id: null, payload: {name: '分页司机' + index}, expected_versions_json: {business_revision: revision}
                });
                const result = await call('/operations/' + prepared.data.id + '/executions', {
                    request_hash: prepared.data.request_hash, confirmed: true
                });
                revision = result.data_revision;
                ids.push(result.data.target_id);
            }
            return ids;
        }""")
        page.get_by_role('link', name='车队资源', exact=True).click()
        expect(page.get_by_text('共 21 条 · 第 1 页', exact=True)).to_be_visible()
        page.get_by_role('button', name='下一页', exact=True).click()
        expect(page.get_by_role('row').filter(has_text='分页司机20')).to_be_visible()
        expect(page.get_by_text('共 21 条 · 第 2 页', exact=True)).to_be_visible()
        page.get_by_role('button', name='上一页', exact=True).click()
        page.get_by_label('效率筛选', exact=True).select_option('HIGH')
        page.get_by_role('button', name='查询', exact=True).click()
        expect(page.get_by_text('共 1 条 · 第 1 页', exact=True)).to_be_visible()
        expect(page.get_by_role('row').filter(has_text='联调司机')).to_be_visible()
        page.route('**/api/v1/drivers?*', lambda route: route.abort())
        page.get_by_role('button', name='刷新', exact=True).click()
        expect(page.get_by_role('alert')).to_contain_text('无法连接本机服务')
        page.unroute('**/api/v1/drivers?*')
        page.get_by_role('button', name='刷新', exact=True).click()
        expect(page.get_by_role('alert')).to_have_count(0)

        page.get_by_role('link', name='请假与维修', exact=True).click()
        page.get_by_role('button', name='新增不可用记录', exact=True).click()
        editor = page.get_by_role('dialog', name='新增不可用记录', exact=True)
        editor.get_by_role('button', name='下一页资源', exact=True).click()
        editor.get_by_label('选择请假维修资源', exact=True).select_option(added_ids[-1])
        editor.get_by_label('不可用开始日期', exact=True).fill(start)
        editor.get_by_label('不可用结束日期', exact=True).fill(start)
        editor.get_by_label('不可用原因', exact=True).fill('分页选人')
        editor.get_by_role('button', name='查看变更', exact=True).click()
        expect(review).to_contain_text(added_ids[-1])
        review_and_execute(page)
        page.get_by_role('row').filter(has_text='分页选人').get_by_role(
            'button', name='取消记录', exact=True
        ).click()
        review_and_execute(page)

        page.get_by_role('link', name='操作记录', exact=True).click()
        expect(page.get_by_role('heading', name='操作记录', exact=True)).to_be_visible()
        page.get_by_role('button', name='查看详情', exact=True).first.click()
        detail = page.get_by_role('dialog', name='操作记录详情', exact=True)
        expect(detail).to_contain_text('车队长')
        expect(detail).to_contain_text('操作前数据')
        detail.get_by_role('button', name='关闭', exact=True).click()
        page.screenshot(path=str(OUTPUT / 'base-data-audit.png'), full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        for link, heading in [
            ('采集类别', '采集类别'),
            ('车队资源', '车队资源'),
            ('请假与维修', '请假与维修'),
            ('操作记录', '操作记录'),
        ]:
            page.get_by_role('link', name=link, exact=True).click()
            expect(page.get_by_role('heading', name=heading, exact=True)).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), link
        page.screenshot(path=str(OUTPUT / 'base-data-mobile.png'), full_page=True)
        page.get_by_role('link', name='车队资源', exact=True).click()
        page.get_by_role('button', name='车辆资料', exact=True).click()
        page.get_by_role('button', name='新增车辆', exact=True).click()
        mobile_editor = page.get_by_role('dialog', name='新增车辆', exact=True)
        expect(mobile_editor.get_by_label('早班 Tag 容量', exact=True)).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        page.screenshot(path=str(OUTPUT / 'base-data-mobile-form.png'), full_page=True)
        mobile_editor.get_by_role('button', name='取消', exact=True).click()
        assert errors == [], errors
        browser.close()
    with closing(sqlite3.connect(database)) as connection:
        counts = {
            table: connection.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
            for table in (
                'collection_categories',
                'drivers',
                'vehicles',
                'resource_unavailability',
                'business_operations',
                'audit_logs',
            )
        }
        assert counts['drivers'] == 21 and counts['vehicles'] == 1 and counts['resource_unavailability'] == 0
        assert (
            connection.execute('SELECT morning_max_tag_count FROM vehicles').fetchone()[0] == 9007199254740993
        )
        assert connection.execute(
            'SELECT middle_max_tag_count,middle_max_road_meters FROM vehicles'
        ).fetchone() == (30, 3333)
        assert connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    return {
        'category_crud': 'passed',
        'driver_qualifications_and_enable': 'passed',
        'vehicle_six_capacities_and_plate_unique': 'passed',
        'leave_maintenance_edit_cancel': 'passed',
        'audit_details': 'passed',
        'desktop_mobile': 'passed',
        'multi_tab_version_conflict': 'passed',
        'lost_execution_response': 'passed',
        'lost_preparation_reload': 'passed',
        'resource_and_picker_pagination': 'passed',
        'page_errors': errors,
        'database_counts': counts,
    }


if __name__ == '__main__':
    batch = '--batch' in sys.argv
    run(
        batch=batch,
        exercise=exercise,
        report_name='base-data-batch-verification.json' if batch else 'base-data-verification.json',
    )
