"""Capture orchestrator controls against an isolated UI server and deterministic task fixtures."""

from scripts.uishot import ui_session


def capture():
    with ui_session(lines=['Orchestrator', 'Implement', 'Review', 'Approved', 'Done', 'Blocked'],
                    out_dir='.ui-current/orchestrator', freeze_animations=True) as ui:
        page = ui.page
        # Isolate the controls from the nested-sandbox preflight banner. This
        # browser fixture changes no server permissions and starts no CLI.
        page.route('**/api/fence/status', lambda route: route.fulfill(json={
            'ok': True, 'backend': 'fixture', 'platform': 'test', 'reason': '', 'remedy': ''}))
        page.reload()
        page.wait_for_selector('.conv-row')
        response = page.request.post(ui.base_url + '/api/presets', headers=ui.auth_headers, data={
            'title': 'Independent reviewer', 'name': 'inspector', 'adapter': 'codex', 'command': 'codex'})
        assert response.ok, response.text()
        page.locator('.conv').filter(has_text='Orchestrator').click()
        page.wait_for_function("() => document.querySelector('#convname').textContent === 'Orchestrator'")
        rows = page.locator('.conv-row')
        index = next(i for i in range(rows.count()) if 'Orchestrator' in rows.nth(i).inner_text())
        ui.open_row_menu(index).get_by_role('menuitem', name='management', exact=True).click()
        page.locator('#captainStyle').select_option('orchestrator')
        page.locator('#defaultReviewPolicy option[value="inspector"]').wait_for(state='attached')
        page.locator('#defaultReviewPolicy').select_option('inspector')
        with page.expect_response(
                lambda r: r.url.endswith('/captain-style') and r.request.method == 'PUT') as saved:
            page.get_by_role('button', name='save captain style', exact=True).click()
        assert saved.value.ok
        page.get_by_text('captain style saved', exact=True).wait_for()
        page.locator('.modal .content').evaluate('(element) => { element.scrollTop = 0; }')
        ui.shot('captain-style-dialog')
        page.get_by_role('button', name='close', exact=True).first.click()
        # Like uishot.seed_room: pin presentation states without launching CLIs.
        page.evaluate("""() => {
          const room = window.partyline.room;
          const root = room.conversations.find(line => line.name === 'Orchestrator');
          const statuses = {Implement: 'implementing', Review: 'in_review',
            Approved: 'approved', Done: 'done', Blocked: 'blocked'};
          room.conversations = room.conversations.map(line => line.id === root.id ? line : ({...line,
            parent_id: root.id, task_status: statuses[line.name], task_round: 3,
            task_root_name: root.name, task_implementer_name: 'builder', task_reviewer_name: 'inspector'}));
          room.conversation = room.conversations.find(line => line.name === 'Review');
        }""")
        page.locator('#task-header').wait_for()
        assert page.locator('.task-status').count() == 5
        assert page.get_by_text('patch in a process', exact=True).count() == 0
        page.locator('#feed .empty').filter(has_text='start talking about this task').wait_for()
        ui.shot('task-rail-and-header')
        ui.element_shot('task-header', '#task-header')
        page.set_viewport_size({'width': 390, 'height': 844})
        ui.shot('task-header-narrow')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.set_viewport_size({'width': 1280, 'height': 800})
        page.get_by_role('button', name='settings', exact=True).click()
        toggle = page.locator('#autoCleanTaskHistory')
        toggle.wait_for()
        page.wait_for_function("!document.querySelector('#autoCleanTaskHistory').disabled")
        toggle.scroll_into_view_if_needed()
        assert not toggle.is_checked()
        ui.shot('task-history-setting')
        return [str(path) for path in ui.shots]


if __name__ == '__main__':
    print('\n'.join(capture()))
