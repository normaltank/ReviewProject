"""Use native disclosure controls, with the same visibility checks as a reader."""


def open_panel(page, panel_id):
    panel = page.locator('#' + panel_id)
    for parent in panel.locator('xpath=ancestor::details').all():
        if parent.get_attribute('open') is None:
            parent.locator(':scope > summary').click()
    if panel.get_attribute('open') is None:
        panel.locator(':scope > summary').click()


def open_editor_tools(page):
    """Open the optional tools when exercising advanced editing workflows."""
    open_panel(page, 'attention-editor')
    for panel_id in ('editor-audit', 'editor-export', 'editor-analysis-details', 'editor-source-position', 'editor-structure', 'editor-expression', 'editor-a-links', 'editor-themes', 'editor-relations'):
        open_panel(page, panel_id)


def open_reading_records(page):
    """Read each record through the visible list, keeping disclosures open."""
    for index in range(page.locator('#focus-list button').count()):
        page.locator('#focus-list button').nth(index).click()
        record = page.locator('#view-detail > details[id^="view-record-"]:not([hidden])')
        if record.count() and record.get_attribute('open') is None:
            record.locator(':scope > summary').click()
