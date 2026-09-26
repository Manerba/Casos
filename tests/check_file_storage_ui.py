"""Browser checks with local assets and mocked APIs; requires Playwright/Chromium."""

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    task = dict(id=1, name="File storage project", task_type="projekt", created_by=1,
                assigned_to=None, description="## Documents", description_format="markdown",
                status="offen", deadline="", priority=50, can_edit_status=True,
                file_storage_type="none", nextcloud_path="")
    saved = []
    state = {"can_write": True, "fail_next": False}
    directory_name = "Team's <documents>"

    def serve(route):
        url = urlparse(route.request.url)
        path = url.path
        status = 200
        data = {"items": []}
        if path == "/":
            route.fulfill(content_type="text/html", body='<html><body data-admin-mode="true"><div id="table"></div></body></html>')
            return
        if path == "/api/tasks/1" and route.request.method == "PUT":
            data = route.request.post_data_json
            if state["fail_next"]:
                state["fail_next"] = False
                status = 500
                data = {"detail": "Storage creation failed"}
            else:
                saved.append(data)
                task.update(data)
                if data.get("file_storage_type") != "webdav":
                    task["nextcloud_path"] = ""
        elif path == "/api/tasks":
            data = {"items": [task]}
        elif path == "/api/nextcloud/directories":
            current = parse_qs(url.query).get("path", [""])[0]
            data = {"directories": [] if current else [{"name": directory_name, "path": directory_name}]}
        elif path == "/api/tasks/1/files":
            data = {"items": [{"name": "Plan.txt", "type": "file", "size": 8, "last_modified": ""}],
                    "storage_type": task["file_storage_type"], "can_write": state["can_write"]}
        route.fulfill(status=status, content_type="application/json", body=json.dumps(data))

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.route("http://tareas.test/**", serve)
        page.goto("http://tareas.test/")
        translations = json.loads((ROOT / "dashboard/static/i18n/en.json").read_text())
        page.evaluate("""translations => window.t = (key, params = {}) => {
            let text = translations[key] || key;
            for (const [name, value] of Object.entries(params)) text = text.replaceAll('{' + name + '}', value);
            return text;
        }""", translations)
        for name in ("expandable_table.js", "wysiwyg_editor.js", "app_core.js", "vendor/marked.umd.js",
                     "vendor/turndown.js", "markdown_editor.js", "file_browser.js", "tab_aufgaben.js"):
            page.add_script_tag(content=(ROOT / "dashboard/static/js" / name).read_text())
        for name in ("style.css", "expandable_table.css", "aufgaben.css", "file_browser.css", "markdown_editor.css"):
            page.add_style_tag(content=(ROOT / "dashboard/static/css" / name).read_text())
        page.add_style_tag(content="body { padding: 25px; } * { animation: none !important; transition: none !important; }")
        page.evaluate("""async () => {
            currentUser = {id: 1, is_admin: false};
            cachedAreas = []; cachedUsers = [];
            aufgabenTable = new ExpandableTable({id: 'filesTest', apiEndpoint: '/api/tasks', expandable: true,
                gridTemplate: '30px 330px 60px 130px 90px 150px 160px', columns: [
                    {field: 'name', align: 'left'}, {field: 'id', align: 'left'},
                    {field: 'status'}, {field: 'priority'}, {field: 'assigned_to_name'}, {field: 'deadline'}
                ], detailFields: []}, 'table', {
                    onRowExpanded: onTaskRowExpanded, onRowCollapsed: deactivateInlineEditing,
                });
            tables.filesTest = aufgabenTable;
            await aufgabenTable.loadData();
        }""")

        def expand():
            page.locator(".table-row > .expand-icon").click()
            expect(page.locator(".detail-edit")).to_be_visible()

        # Local creation is offered when Nextcloud is not configured.
        expand()
        page.get_by_role("button", name="File Storage", exact=True).click()
        expect(page.locator("#fileStorageType")).to_have_value("local")
        expect(page.locator('#fileStorageType option[value="webdav"]')).to_be_disabled()
        expect(page.locator("#webdavStorageBrowser")).to_be_hidden()
        expect(page.locator("#localStorageSave")).to_be_visible()
        state["fail_next"] = True
        page.locator("#localStorageSave").click()
        expect(page.locator("#localStorageSave")).to_be_enabled()
        expect(page.locator(".modal-overlay")).to_be_visible()
        page.locator("#localStorageSave").click()
        expect(page.locator(".modal-overlay")).to_have_count(0)
        assert saved[-1] == {"file_storage_type": "local"}
        expand()
        expect(page.locator("#fileBrowserContainer_1")).to_be_visible()
        expect(page.locator("#fb-upload-1")).to_be_visible()
        expect(page.locator(".fb-tree-name")).to_have_text("Plan.txt")

        # WebDAV browsing handles names containing quotes and HTML as plain text.
        page.evaluate("ncConfigured = true")
        page.get_by_role("button", name="📂 Local file storage", exact=True).click()
        page.locator("#fileStorageType").select_option("webdav")
        expect(page.locator("#localStorageSave")).to_be_hidden()
        page.locator(".nc-dir-name").click()
        expect(page.locator("#ncBrowseBc")).to_contain_text(directory_name)
        expect(page.locator(".nc-select-btn")).to_be_visible()
        page.locator("#fileStorageType").select_option("local")
        expect(page.locator(".nc-select-btn")).to_have_count(0)
        page.locator("#fileStorageType").select_option("webdav")
        page.locator(".nc-dir-select-btn").click()
        expect(page.locator(".modal-overlay")).to_have_count(0)
        assert saved[-1] == {"file_storage_type": "webdav", "nextcloud_path": directory_name}
        expand()
        expect(page.locator("#fileBrowserContainer_1")).to_be_visible()
        page.get_by_role("button", name="📂 " + directory_name, exact=True).click()
        page.locator("#storageRemove").click()
        expect(page.locator(".modal-overlay")).to_have_count(0)
        assert saved[-1] == {"file_storage_type": "none"}
        expand()
        expect(page.locator("#fileBrowserContainer_1")).to_have_count(0)

        # Ordinary tasks also offer local storage without Nextcloud.
        task["task_type"] = "aufgabe"
        page.evaluate("async () => { ncConfigured = false; await aufgabenTable.loadData(); }")
        expand()
        page.get_by_role("button", name="File Storage", exact=True).click()
        page.locator("#localStorageSave").click()
        expect(page.locator(".modal-overlay")).to_have_count(0)
        expand()
        expect(page.locator("#fileBrowserContainer_1")).to_be_visible()

        # Read-only users see files, but no upload, rename, delete or mapping actions.
        state["can_write"] = False
        task.update(created_by=2, is_team_member=True, can_edit_status=False)
        page.evaluate("async () => { await aufgabenTable.loadData(); }")
        expand()
        expect(page.locator(".fb-tree-name")).to_have_text("Plan.txt")
        expect(page.locator("#fb-upload-1")).to_be_hidden()
        expect(page.locator("#fb-mkdir-1")).to_be_hidden()
        expect(page.locator("button.nc-active")).to_have_count(0)
        page.locator(".fb-tree-name").click(button="right")
        expect(page.locator('.fb-ctx-item[data-action="download"]')).to_be_visible()
        expect(page.locator('.fb-ctx-item[data-action="rename"]')).to_have_count(0)
        expect(page.locator('.fb-ctx-item[data-action="delete"]')).to_have_count(0)
        assert errors == [], errors
        browser.close()
    print("File storage browser checks passed: tasks/projects, local without Nextcloud, creation retry, WebDAV selection, switching, unlinking and reader permissions.")


if __name__ == "__main__":
    main()
