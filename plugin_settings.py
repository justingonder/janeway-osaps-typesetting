from utils import plugins
from utils.install import update_settings

PLUGIN_NAME = "OS-APS Typesetting"
DISPLAY_NAME = "OS-APS Typesetting"
DESCRIPTION = "Typesetting workflow stage integrating the OS-APS publishing suite"
AUTHOR = "CDL"
VERSION = "0.1"
SHORT_NAME = "osaps_typesetting"
MANAGER_URL = "osaps_typesetting_manager"
JANEWAY_VERSION = "1.8"

# Workflow Settings
IS_WORKFLOW_PLUGIN = True
JUMP_URL = "osaps_typesetting_article"
HANDSHAKE_URL = "osaps_typesetting_articles"
ARTICLE_PK_IN_HANDSHAKE_URL = True
STAGE = "osaps_typesetting"
KANBAN_CARD = "osaps_typesetting/elements/card.html"
DASHBOARD_TEMPLATE = "osaps_typesetting/elements/dashboard.html"

SETTINGS_PATH = "plugins/osaps_typesetting/install/settings.json"


class OSAPSTypesettingPlugin(plugins.Plugin):
    plugin_name = PLUGIN_NAME
    display_name = DISPLAY_NAME
    description = DESCRIPTION
    author = AUTHOR
    short_name = SHORT_NAME
    manager_url = MANAGER_URL

    version = VERSION
    janeway_version = JANEWAY_VERSION

    is_workflow_plugin = IS_WORKFLOW_PLUGIN
    jump_url = JUMP_URL
    handshake_url = HANDSHAKE_URL
    article_pk_in_handshake_url = ARTICLE_PK_IN_HANDSHAKE_URL
    stage = STAGE
    kanban_card = KANBAN_CARD


def install():
    OSAPSTypesettingPlugin.install()
    update_settings(file_path=SETTINGS_PATH)


def hook_registry():
    return {}
