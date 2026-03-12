from ayon_server.addons import BaseServerAddon

from .settings import CavalrySettings, DEFAULT_CAVALRY_SETTING


class Cavalry(BaseServerAddon):
    settings_model = CavalrySettings

    async def get_default_settings(self):
        settings_model_cls = self.get_settings_model()
        return settings_model_cls(**DEFAULT_CAVALRY_SETTING)
