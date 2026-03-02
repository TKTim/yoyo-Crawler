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
        db_table = 'foodlinebot_parsedarticle'  # Keep old table name after app rename


class AuthorizedUser(models.Model):
    """Authorized users who can use protected bot commands."""
    user_id = models.CharField(max_length=100, unique=True)
    label = models.CharField(max_length=100, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.label} ({self.user_id})" if self.label else self.user_id


class PushTarget(models.Model):
    """Users/groups that receive cron push notifications."""
    target_id = models.CharField(max_length=100, unique=True)
    label = models.CharField(max_length=100, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.label} ({self.target_id})" if self.label else self.target_id
