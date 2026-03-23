"""
Management command to setup GitHub Gist for persistent storage.
Handles articles, authorized users, push targets, and dietary data.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Setup GitHub Gist for persistent storage (articles, users, targets, dietary)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--create',
            action='store_true',
            help='Create a new Gist (requires GITHUB_GIST_TOKEN env var)',
        )
        parser.add_argument(
            '--save',
            action='store_true',
            help='Save all DB data to Gist',
        )
        parser.add_argument(
            '--load',
            action='store_true',
            help='Load all data from Gist into DB',
        )

    def handle(self, *args, **options):
        from mylinebot_code.gist_storage import (
            create_gist,
            save_articles_to_gist,
            load_articles_from_gist,
            save_users_to_gist,
            load_users_from_gist,
            save_targets_to_gist,
            load_targets_from_gist,
            save_dietary_to_gist,
            load_dietary_from_gist,
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

            results = {
                'Articles': save_articles_to_gist(),
                'Users': save_users_to_gist(),
                'Targets': save_targets_to_gist(),
                'Dietary': save_dietary_to_gist(),
            }
            for name, ok in results.items():
                if ok:
                    self.stdout.write(self.style.SUCCESS(f'{name} saved to Gist'))
                else:
                    self.stderr.write(self.style.ERROR(f'Failed to save {name} to Gist'))

        elif options['load']:
            if not GITHUB_TOKEN or not GIST_ID:
                self.stderr.write(self.style.ERROR(
                    'Missing GITHUB_GIST_TOKEN or GIST_ID. Run --create first.'
                ))
                return

            results = {
                'Articles': load_articles_from_gist(),
                'Users': load_users_from_gist(),
                'Targets': load_targets_from_gist(),
                'Dietary': load_dietary_from_gist(),
            }
            for name, ok in results.items():
                if ok:
                    self.stdout.write(self.style.SUCCESS(f'{name} loaded from Gist'))
                else:
                    self.stderr.write(self.style.WARNING(f'{name} skipped (already has data or failed)'))

        else:
            self.stdout.write('Usage:')
            self.stdout.write('  python manage.py setup_gist --create  # Create new Gist')
            self.stdout.write('  python manage.py setup_gist --save    # Save all DB data to Gist')
            self.stdout.write('  python manage.py setup_gist --load    # Load all data from Gist to DB')
            self.stdout.write('')
            self.stdout.write('Current config:')
            self.stdout.write(f'  GITHUB_GIST_TOKEN: {"[SET]" if GITHUB_TOKEN else "[NOT SET]"}')
            self.stdout.write(f'  GIST_ID: {GIST_ID or "[NOT SET]"}')
