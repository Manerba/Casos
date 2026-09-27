"""Browserpruefung: Teilaufgaben zuklappen, ohne die Zeile zu verschieben.

Nutzt lokale Assets, gemockte APIs und die optionale Playwright-Installation.
"""

import asyncio
import json
import mimetypes
import sys
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dashboard.api_tasks import get_tasks_config


def main():
    config = asyncio.run(get_tasks_config())
    project = dict(id=1, name='Scrollposition', task_type='projekt', created_by=1,
                   assigned_to=None, description='', status='offen', priority=50,
                   deadline='', can_edit_status=True)
    subtasks = [dict(id=index, name=f'Teilaufgabe {index}', project_id=1,
                     position_number=index - 100, status_percent=0, priority=50,
                     deadline='', predecessor_ids=[], description_format='markdown',
                     description='\n\n'.join(f'Absatz {line} der Beschreibung.' for line in range(30)))
                for index in range(101, 129)]
    subtasks[3]['name'] = 'Eine Teilaufgabe mit einem langen Namen, der sich bei schmaler Tabelle ueber mehrere Zeilen verteilt'

    def serve(route):
        path = urlparse(route.request.url).path
        if route.request.resource_type == 'document':
            route.fulfill(content_type='text/html', body=(ROOT / 'dashboard/templates/index.html').read_text())
            return
        if path.startswith('/static/'):
            file = ROOT / 'dashboard' / path.lstrip('/')
            route.fulfill(content_type=mimetypes.guess_type(file)[0] or 'application/octet-stream', body=file.read_bytes())
            return
        data = {'items': []}
        if path == '/api/tasks/config':
            data = config
        elif path == '/api/tasks':
            data = {'items': [project, {**project, 'id': 2, 'name': 'Weiteres Projekt'}]}
        elif path == '/api/auth/me':
            data = {'user': {'id': 1, 'is_admin': True, 'username': 'test'}}
        elif path == '/api/nextcloud/status':
            data = {'configured': False}
        elif path == '/api/tasks/1/subtasks':
            data = {'items': subtasks}
        route.fulfill(content_type='application/json', body=json.dumps(data))

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width, height in [(1440, 900), (800, 700)]:
            page = browser.new_page(viewport={'width': width, 'height': height})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('http://tareas.test/**', serve)
            page.goto('http://tareas.test/aufgaben')
            project_row = page.locator('[data-row-id="1"]')
            project_row.locator(':scope > .table-row > .expand-icon').click()
            expect(page.locator('.subtask-row')).to_have_count(len(subtasks))

            def settle():
                page.evaluate('''() => new Promise(resolve =>
                    requestAnimationFrame(() => requestAnimationFrame(() => requestAnimationFrame(resolve))))''')

            def row(subtask_id):
                return page.locator(f'tr[data-subtask-id="{subtask_id}"]')

            def expand(subtask_id):
                row(subtask_id).locator('.subtask-expand-icon').click()
                expect(page.locator(f'#stWysiwyg_{subtask_id} .markdown-body')).to_be_visible()
                page.wait_for_function('''id => {
                    const notes = document.getElementById(`stAllNotesContent_${id}`);
                    return notes._loaded && !notes.textContent.includes('Laden');
                }''', arg=subtask_id)
                settle()

            def collapse_at(subtask_id, top=180):
                # Position before clicking; mouse.click cannot auto-scroll like locator.click.
                row(subtask_id).evaluate('(el, top) => window.scrollBy(0, el.getBoundingClientRect().top - top)', top)
                settle()
                before = row(subtask_id).bounding_box()['y']
                icon = row(subtask_id).locator('.subtask-expand-icon').bounding_box()
                page.mouse.click(icon['x'] + icon['width'] / 2, icon['y'] + icon['height'] / 2)
                expect(page.locator(f'tr[data-subtask-detail-id="{subtask_id}"]')).to_be_hidden()
                settle()
                after = row(subtask_id).bounding_box()['y']
                assert abs(after - before) < 1, (width, subtask_id, before, after)

            # Near the end, the viewport needs space below the project after collapse.
            expand(128)
            collapse_at(128)
            assert project_row.bounding_box()['y'] + project_row.bounding_box()['height'] < height - 100
            first_height = page.evaluate('document.documentElement.scrollHeight')
            for _ in range(3):
                expand(128)
                collapse_at(128)
                assert abs(page.evaluate('document.documentElement.scrollHeight') - first_height) < 2
            expand(128)
            collapse_at(128, top=height - 200)

            # Several open rows can be collapsed in succession without accumulating space.
            expand(127)
            expand(128)
            collapse_at(128)
            collapse_at(127)

            # Scrolling up releases the extra space; an earlier row needs no extra space.
            page.evaluate('window.scrollTo(0, 0)')
            settle()
            body = page.locator('#aufgabenTableContainer > .table-body')
            assert abs(body.bounding_box()['height'] - project_row.bounding_box()['height']) < 2
            expand(101)
            collapse_at(101)
            assert abs(body.bounding_box()['height'] - project_row.bounding_box()['height']) < 2

            # Closing the project and navigating home both restore the ordinary list height.
            expand(128)
            collapse_at(128)
            page.evaluate('aufgabenTable.toggleRow("1")')
            settle()
            assert page.evaluate('document.documentElement.scrollHeight') == height
            project_row.locator(':scope > .table-row > .expand-icon').click()
            expect(page.locator('.subtask-row')).to_have_count(len(subtasks))
            settle()
            assert abs(body.bounding_box()['height'] - project_row.bounding_box()['height']) < 2
            expand(128)
            collapse_at(128)
            page.locator('.header-home').click()
            expect(page.locator('.project-focus.expanded')).to_have_count(0)
            settle()
            assert page.evaluate('document.documentElement.scrollHeight') == height
            assert errors == [], errors
            page.close()
        browser.close()
    print('Subtask scroll checks passed: stable rows, space below the frame, repeated toggles, scrolling up and project/list navigation at two viewport sizes.')


if __name__ == '__main__':
    main()
