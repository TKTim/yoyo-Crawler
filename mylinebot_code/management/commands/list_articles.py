from django.core.management.base import BaseCommand
from mylinebot_code.models import ParsedArticle


class Command(BaseCommand):
    help = 'List articles from database'

    def add_arguments(self, parser):
        parser.add_argument(
            '--all',
            action='store_true',
            help='Show all articles (default: today only)',
        )
        parser.add_argument(
            '--date',
            type=str,
            help='Filter by date (YYYY-MM-DD)',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=20,
            help='Limit number of results (default: 20)',
        )

    def handle(self, *args, **options):
        from datetime import date, datetime

        queryset = ParsedArticle.objects.all()

        if options['date']:
            try:
                filter_date = datetime.strptime(options['date'], '%Y-%m-%d').date()
                queryset = queryset.filter(post_date=filter_date)
                self.stdout.write(f'Articles for {filter_date}:')
            except ValueError:
                self.stdout.write(self.style.ERROR('Invalid date format. Use YYYY-MM-DD'))
                return
        elif not options['all']:
            queryset = queryset.filter(post_date=date.today())
            self.stdout.write(f'Articles for today ({date.today()}):')
        else:
            self.stdout.write('All articles:')

        queryset = queryset[:options['limit']]

        if not queryset:
            self.stdout.write(self.style.WARNING('No articles found.'))
            return

        self.stdout.write('')
        for article in queryset:
            self.stdout.write(f'Date: {article.post_date}')
            self.stdout.write(f'Title: {article.title}')
            self.stdout.write(f'URL: {article.url}')
            self.stdout.write(f'Added: {article.created_at}')
            self.stdout.write('-' * 50)
