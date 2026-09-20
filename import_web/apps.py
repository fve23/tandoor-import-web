from django.apps import AppConfig


class ImportWebPluginConfig(AppConfig):
    name = 'recipes.plugins.import_web'
    label = 'import_web'
    verbose_name = 'Import Web'
    VERSION = '0.1.0'
    base_url = 'import-web/'
    api_router_name = 'import_web_router'

    def ready(self):
        pass
