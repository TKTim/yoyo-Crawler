from django.core.management.base import BaseCommand
from foodlinebot.scraper import parse_forum


class Command(BaseCommand):
    help = 'Parse yoyo.club.tw forum for new articles posted today'

    def handle(self, *args, **options):
        self.stdout.write('Parsing forum...')

        new_articles = parse_forum()

        if new_articles:
            self.stdout.write(
                self.style.SUCCESS(f'Found {len(new_articles)} new article(s):')
            )
            for article in new_articles:
                self.stdout.write(f'  - {article.title}')
                self.stdout.write(f'    {article.url}')
        else:
            self.stdout.write(self.style.WARNING('No new articles found today.'))
