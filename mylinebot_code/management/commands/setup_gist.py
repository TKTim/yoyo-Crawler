"""
Management command to setup GitHub Gist for article storage.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Setup GitHub Gist for persistent article storage'

    def add_arguments(self, parser):
        parser.add_argument(
            '--create',
            action='store_true',
            help='Create a new Gist (requires GITHUB_GIST_TOKEN env var)',
        )
        parser.add_argument(
            '--save',
            action='store_true',
            help='Save current DB articles to Gist',
        )
        parser.add_argument(
            '--load',
            action='store_true',
            help='Load articles from Gist into DB',
        )

    def handle(self, *args, **options):
        from mylinebot_code.gist_storage import (
            create_gist,
            save_articles_to_gist,
            load_articles_from_gist,
            GITHUB_TOKEN,
            GIST_ID,
        )

        if options['create']:
            if not GITHUB_TOKEN:
                self.stderr.write(self.style.ERROR(
                    'GITHUB_GIST_TOKEN not set. Create one at:\n'
                    'https://github.com/settings/tokens/new?scopes=gist&description=YoYo-Bot'
                ))
                return

            gist_id = create_gist()
            if gist_id:
                self.stdout.write(self.style.SUCCESS(f'Gist created! Add to .env:'))
                self.stdout.write(f'GIST_ID={gist_id}')

        elif options['save']:
            if not GITHUB_TOKEN or not GIST_ID:
                self.stderr.write(self.style.ERROR(
                    'Missing GITHUB_GIST_TOKEN or GIST_ID. Run --create first.'
                ))
                return

            if save_articles_to_gist():
                self.stdout.write(self.style.SUCCESS('Articles saved to Gist'))
            else:
                self.stderr.write(self.style.ERROR('Failed to save to Gist'))

        elif options['load']:
            if not GITHUB_TOKEN or not GIST_ID:
                self.stderr.write(self.style.ERROR(
                    'Missing GITHUB_GIST_TOKEN or GIST_ID. Run --create first.'
                ))
                return

            if load_articles_from_gist():
                self.stdout.write(self.style.SUCCESS('Articles loaded from Gist'))
            else:
                self.stderr.write(self.style.ERROR('Failed to load from Gist'))

        else:
            self.stdout.write('Usage:')
            self.stdout.write('  python manage.py setup_gist --create  # Create new Gist')
            self.stdout.write('  python manage.py setup_gist --save    # Save DB to Gist')
            self.stdout.write('  python manage.py setup_gist --load    # Load Gist to DB')
            self.stdout.write('')
            self.stdout.write('Current config:')
            self.stdout.write(f'  GITHUB_GIST_TOKEN: {"[SET]" if GITHUB_TOKEN else "[NOT SET]"}')
            self.stdout.write(f'  GIST_ID: {GIST_ID or "[NOT SET]"}')
