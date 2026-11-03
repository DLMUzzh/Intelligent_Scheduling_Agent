"""Exercise the static prototype in isolated, headless browser contexts."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
SCREENSHOTS = ROOT / "screenshots"
STORAGE_KEY = "fleetwise.prototype.v1"


def saved(page):
    return page.evaluate("key => JSON.parse(localStorage.getItem(key))", STORAGE_KEY)


def selected_day(page, date="2026-11-04"):
    return saved(page)["plans"][0]["days"][date]


def close_dialog(page):
    page.locator('#modal [data-action="close-dialog"]').last.click()


def new_page(browser, errors):
    context = browser.new_context(viewport={"width": 1440, "height": 1050})
    page = context.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto((ROOT / "index.html").as_uri())
    page.wait_for_load_state("networkidle")
    expect(page.locator("h1")).to_have_text("排班工作台")
    return context, page


def main():
    SCREENSHOTS.mkdir(exist_ok=True)
    errors = []
    checks = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context, page = new_page(browser, errors)
        page.screenshot(path=str(SCREENSHOTS / "desktop.png"), full_page=True, animations="disabled")
        for view in ["plans", "resources", "history", "reports", "logs", "workbench"]:
            page.locator(f'[data-view="{view}"]').click()
            expect(page.locator("h1")).to_be_visible()
        checks.append("six-page navigation")
        page.locator(".pack-card").first.click()
        original = selected_day(page)["draft"]
        page.locator("[data-pack-qty]").first.fill("1000")
        page.locator('[data-action="save-pack"]').click()
        expect(page.locator("#form-error")).to_contain_text("超出")
        assert selected_day(page)["draft"] == original
        page.locator("[data-pack-qty]").first.fill("99")
        page.locator('[data-action="save-pack"]').click()
        expect(page.locator("#modal")).not_to_be_visible()
        assert selected_day(page)["draft"][0]["items"][0]["qty"] == 99
        checks.append("invalid edit preserves draft; valid edit persists")
        page.reload()
        expect(page.locator(".pack-card").first).to_contain_text("99")
        page.locator('[data-action="confirm-day"]').click()
        expect(page.locator("#modal")).to_contain_text("存在未分配需求")
        page.locator('[data-action="confirm-dialog"]').click()
        assert selected_day(page)["formal"] is not None
        checks.append("partial-demand confirmation and persistence")
        page.locator(".pack-card").first.click()
        page.locator("#pack-driver").select_option("D020")
        expect(page.locator("#pack-diff")).to_contain_text("张三")
        expect(page.locator("#pack-diff")).to_contain_text("许阳")
        assert selected_day(page)["formal"][0]["driverId"] == "D001"
        page.screenshot(path=str(SCREENSHOTS / "change-review.png"), animations="disabled")
        page.locator('[data-action="save-pack"]').click()
        assert selected_day(page)["formal"][0]["driverId"] == "D020"
        assert len(selected_day(page)["history"]) >= 2
        checks.append("formal changes display diff and preserve history")
        page.locator('[data-view="history"]').click()
        page.locator("#history-driver").select_option("D020")
        page.locator("#history-status").select_option("confirmed")
        page.locator("#history-missing").check()
        expect(page.locator("tbody tr")).to_have_count(1)
        expect(page.locator("tbody")).to_contain_text("2026-11-04")
        page.locator('[data-action="history-filter-clear"]').click()
        page.locator('[data-view="workbench"]').click()
        checks.append("history driver, status and unallocated-demand filters")
        page.locator('[data-action="cancel-day"]').click()
        page.locator('[data-action="confirm-dialog"]').click()
        assert selected_day(page)["formal"] is None
        page.locator('[data-action="generate-day"]').first.click()
        page.locator('[data-action="confirm-day"]').click()
        page.locator('[data-action="confirm-dialog"]').click()
        assert selected_day(page)["formal"]
        checks.append("cancel releases schedule and allows reconfirmation")
        context.close()

        context, page = new_page(browser, errors)
        page.locator('[data-action="batch-confirm"]').click()
        page.locator('[data-action="batch-submit"]').click()
        page.locator('[data-action="confirm-dialog"]').click()
        expect(page.locator("#form-error")).to_contain_text("全部未生效")
        assert selected_day(page)["formal"] is None
        assert selected_day(page, "2026-11-03")["formal"]
        close_dialog(page)
        page.locator('[data-action="batch-generate"]').click()
        page.locator('[data-action="batch-submit"]').click()
        page.locator('[data-action="batch-confirm"]').click()
        page.locator('[data-action="batch-submit"]').click()
        page.locator('[data-action="confirm-dialog"]').click()
        expect(page.locator("#modal")).not_to_be_visible()
        assert all(day["formal"] for day in saved(page)["plans"][0]["days"].values())
        page.locator('[data-action="batch-confirm"]').click()
        page.locator('[data-action="batch-submit"]').click()
        before = len(saved(page)["logs"])
        page.locator('[data-action="confirm-dialog"]').click()
        expect(page.locator("#toast-region")).to_contain_text("ALREADY_CONFIRMED")
        assert len(saved(page)["logs"]) == before
        checks.append("atomic batch validation, skip confirmed dates, duplicate confirmation")
        context.close()

        context, page = new_page(browser, errors)
        page.locator('[data-view="resources"]').click()
        page.locator("#resource-date").fill("2026-12-01")
        expect(page.locator("#resource-date")).to_have_value("2026-12-01")
        page.locator('#resource-search').fill("张三")
        page.locator('[data-action="unavailable"][data-id="D001"]').click()
        page.locator("#off-start").fill("2026-11-03")
        page.locator("#off-end").fill("2026-11-03")
        page.locator('[data-action="save-unavailable"]').click()
        expect(page.locator("#form-error")).to_contain_text("2026-11-03")
        assert not saved(page)["drivers"][0]["unavailable"]
        close_dialog(page)
        page.locator('#resource-search').fill("")
        page.locator('[data-action="new-resource"]').click()
        page.locator("#resource-name").fill("交互验证司机")
        expect(page.locator("#resource-grade")).to_have_value("MEDIUM")
        page.locator('[data-action="save-resource"]').click()
        assert saved(page)["drivers"][-1]["name"] == "交互验证司机"
        checks.append("resource change protects formal schedule; resource creation")
        page.screenshot(path=str(SCREENSHOTS / "resources.png"), full_page=True, animations="disabled")
        page.locator('[data-view="plans"]').click()
        page.locator('[data-action="new-plan"]').click()
        page.locator("#plan-name").fill("原型交互验证计划")
        page.locator("#plan-start").fill("2026-11-04")
        page.locator("#plan-end").fill("2026-11-06")
        page.locator('[data-action="wizard-next"]').click()
        expect(page.locator("#form-error")).to_contain_text("日期重叠")
        page.locator("#plan-start").fill("2026-11-10")
        page.locator("#plan-end").fill("2026-11-12")
        page.locator('[data-action="wizard-next"]').click()
        page.locator('[data-action="move-demand"][data-group="base"][data-index="0"][data-direction="1"]').click()
        expect(page.locator('[data-demand-group="base"] [data-demand-category]').first).to_have_value("R1")
        page.locator('[data-action="move-demand"][data-group="base"][data-index="1"][data-direction="-1"]').click()
        page.locator("#override-enabled").check()
        page.locator('[data-demand-group="override"] [data-demand-qty]').first.fill("50")
        page.locator("#override-date").select_option("2026-11-11")
        page.locator('[data-demand-group="override"] [data-demand-qty]').first.fill("75")
        page.locator('[data-action="wizard-next"]').click()
        page.locator('[data-action="wizard-save"]').click()
        plan = saved(page)["plans"][0]
        assert plan["days"]["2026-11-10"]["demands"][0]["qty"] == 50
        assert plan["days"]["2026-11-11"]["demands"][0]["qty"] == 75
        assert plan["days"]["2026-11-12"]["demands"][0]["qty"] == 200
        checks.append("plan overlap, demand ordering and per-day overrides")
        context.close()

        context, page = new_page(browser, errors)
        page.locator('.heading-actions [data-action="agent-toggle"]').click()
        page.locator("#agent-input").fill("将张三的效率等级改为低")
        page.locator("#agent-form").evaluate("form => form.requestSubmit()")
        expect(page.locator(".agent-pending")).to_be_visible()
        assert saved(page)["drivers"][0]["grade"] == "HIGH"
        page.screenshot(path=str(SCREENSHOTS / "agent.png"), animations="disabled")
        page.locator('[data-action="agent-confirm"]').click()
        assert saved(page)["drivers"][0]["grade"] == "LOW"
        assert saved(page)["logs"][0]["origin"] == "Agent"
        checks.append("Agent changes require explicit confirmation")
        page.locator('#agent-panel [data-action="agent-toggle"]').click()
        page.locator('[data-action="settings"]').first.click()
        page.locator('[data-action="demo-history"]').click()
        expect(page.locator(".notice").first).to_contain_text("已锁定")
        assert page.locator('[data-action="generate-day"]').count() == 0
        page.locator(".pack-card").first.click()
        expect(page.locator("#modal")).to_contain_text("历史信息只读")
        assert page.locator('[data-action="save-pack"]').count() == 0
        checks.append("historical dates are read-only")
        context.close()

        context, page = new_page(browser, errors)
        page.set_viewport_size({"width": 390, "height": 844})
        expect(page.locator("h1")).to_have_text("排班工作台")
        page.screenshot(path=str(SCREENSHOTS / "mobile.png"), full_page=True, animations="disabled")
        assert page.evaluate("document.body.scrollWidth <= innerWidth")
        for view in ["resources", "history", "reports", "logs", "plans"]:
            page.locator(f'[data-view="{view}"]').click()
            assert page.evaluate("document.body.scrollWidth <= innerWidth"), view
        page.locator('[data-view="plans"]').click()
        expect(page.locator("h1")).to_have_text("采集计划")
        page.locator('[data-action="new-plan"]').click()
        expect(page.locator("#plan-name")).to_be_visible()
        close_dialog(page)
        checks.append("mobile layout and navigation")
        context.close()

        context, page = new_page(browser, errors)
        page.locator(".pack-card").first.click()
        page.locator("[data-pack-qty]").first.fill("99")
        other = context.new_page()
        other.on("pageerror", lambda error: errors.append(str(error)))
        other.goto((ROOT / "index.html").as_uri())
        other.wait_for_load_state("networkidle")
        other.locator('[data-view="resources"]').click()
        other.locator('[data-action="new-resource"]').click()
        other.locator("#resource-name").fill("跨页面验证司机")
        other.locator('[data-action="save-resource"]').click()
        expect(page.locator("#stale-banner")).to_be_visible()
        page.locator('[data-action="save-pack"]').click()
        expect(page.locator("#form-error")).to_contain_text("数据已发生变化")
        assert selected_day(page)["draft"][0]["items"][0]["qty"] == 100
        checks.append("stale page cannot overwrite newer data")
        context.close()

        context, page = new_page(browser, errors)
        page.locator('[data-action="settings"]').first.click()
        page.locator('[data-action="demo-blank"]').click()
        page.locator('[data-action="confirm-dialog"]').click()
        data = saved(page)
        assert not data["plans"] and not data["drivers"] and not data["vehicles"]
        page.locator('[data-action="new-plan"]').first.click()
        page.locator("#plan-name").fill("空白场景计划")
        page.locator('[data-action="wizard-next"]').click()
        page.locator('[data-action="wizard-next"]').click()
        page.locator('[data-action="wizard-save"]').click()
        page.locator('[data-action="open-plan"]').click()
        page.locator('[data-action="generate-day"]').first.click()
        assert saved(page)["plans"][0]["days"]["2026-11-03"]["draft"] == []
        expect(page.locator('[data-action="confirm-day"]')).to_be_disabled()
        checks.append("empty initialization and zero-resource empty-draft protection")
        context.close()

        context, page = new_page(browser, errors)
        page.locator(".pack-card").first.click()
        page.locator("[data-pack-qty]").first.fill("90")
        page.locator('[data-action="save-pack"]').click()
        page.locator('[data-action="add-pack"]').first.click()
        page.locator("[data-pack-qty]").first.fill("10")
        page.locator('[data-action="save-pack"]').click()
        expect(page.locator("#modal")).not_to_be_visible()
        assert len(selected_day(page)["draft"]) == 14
        added_id = selected_day(page)["draft"][-1]["id"]
        page.locator(f'[data-action="edit-pack"][data-id="{added_id}"]').click()
        page.locator('[data-action="delete-pack"]').click()
        page.locator('[data-action="confirm-dialog"]').click()
        assert len(selected_day(page)["draft"]) == 13
        checks.append("add and delete task packages using free resources")
        context.close()
        browser.close()
    assert not errors, errors
    result = {"passed": len(checks), "checks": checks, "browser_errors": errors}
    (SCREENSHOTS / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
