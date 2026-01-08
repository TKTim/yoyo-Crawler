from django.apps import AppConfig


class MylinebotCodeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'mylinebot_code'

    def ready(self):
        """Load articles from Gist on startup (for Render's ephemeral filesystem)."""
        import os
        # Only run in main process, not in migrations or shell
        if os.environ.get('RUN_MAIN') != 'true' and not os.environ.get('RENDER'):
            return

        try:
            from .gist_storage import load_articles_from_gist
            load_articles_from_gist()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Failed to load from Gist on startup: {e}")
