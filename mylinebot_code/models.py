from django.db import models


class ParsedArticle(models.Model):
    """Store parsed articles to avoid duplicates."""
    title = models.CharField(max_length=500)
    url = models.URLField(unique=True)
    post_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title

    class Meta:
        ordering = ['-post_date', '-created_at']
