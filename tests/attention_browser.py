"""Use native disclosure controls, with the same visibility checks as a reader."""


def open_panel(page, panel_id):
    panel = page.locator('#' + panel_id)
    if panel.get_attribute('open') is None:
        panel.locator(':scope > summary').click()
