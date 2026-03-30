from django.db import models


class ParsedArticle(models.Model):
    """Store parsed articles to avoid duplicates."""
    title = models.CharField(max_length=500)
    url = models.URLField(unique=True)
    post_date = models.DateField()
    author = models.CharField(max_length=200, blank=True, default='')
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


class FoodEntry(models.Model):
    """One row per food item logged by a user."""
    user_id = models.CharField(max_length=100, db_index=True)
    date = models.DateField(db_index=True)
    name = models.CharField(max_length=200)
    description = models.CharField(max_length=500, blank=True, default='')
    calories = models.FloatField(null=True)
    protein = models.FloatField(null=True)
    carbs = models.FloatField(null=True)
    fat = models.FloatField(null=True)
    basis = models.CharField(max_length=200, blank=True, default='')
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-added_at']

    def __str__(self):
        return f"{self.user_id} - {self.date} - {self.name}"


class UserTdee(models.Model):
    """One row per user's TDEE setting."""
    user_id = models.CharField(max_length=100, unique=True)
    tdee = models.IntegerField()

    def __str__(self):
        return f"{self.user_id}: {self.tdee} kcal"


class UserProfile(models.Model):
    """Member profile for BMR/TDEE calculation."""
    user_id = models.CharField(max_length=100, unique=True)
    gender = models.CharField(max_length=10)       # 'male' / 'female'
    height = models.FloatField()                    # cm
    weight = models.FloatField()                    # kg
    age = models.IntegerField()
    activity_level = models.CharField(max_length=20, blank=True, default='')
    goal = models.CharField(max_length=20, blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)
    streak_count = models.IntegerField(default=0)
    streak_last_date = models.DateField(null=True, blank=True)

    def calculate_bmr(self):
        """Mifflin-St Jeor formula."""
        if self.gender == 'male':
            return (10 * self.weight) + (6.25 * self.height) - (5 * self.age) + 5
        return (10 * self.weight) + (6.25 * self.height) - (5 * self.age) - 161

    def calculate_tdee(self):
        multipliers = {
            'sedentary': 1.2, 'light': 1.375, 'moderate': 1.55,
            'active': 1.725, 'very_active': 1.9,
        }
        return self.calculate_bmr() * multipliers.get(self.activity_level, 1.2)

    def __str__(self):
        return f"{self.user_id}: {self.gender} {self.height}cm {self.weight}kg"
