"""
CRUD for UserProfile, with Gist write-through backup.
Follows the same lazy-import pattern as dietary_storage.py.
"""
import logging

logger = logging.getLogger(__name__)


def get_profile(user_id):
    """Return UserProfile instance or None."""
    from .models import UserProfile

    return UserProfile.objects.filter(user_id=user_id).first()


def save_profile(user_id, data):
    """
    Create or update a user profile from a dict with keys:
    gender, height, weight, age.
    Syncs to Gist after save.
    """
    from .models import UserProfile
    from .gist_storage import save_profiles_to_gist

    UserProfile.objects.update_or_create(
        user_id=user_id,
        defaults={
            'gender': data['gender'],
            'height': data['height'],
            'weight': data['weight'],
            'age': data['age'],
        },
    )

    save_profiles_to_gist()
    return True


def update_profile_goal(user_id, activity_level, goal):
    """
    Update activity_level and goal on an existing profile.
    Syncs to Gist after save.
    Returns True on success, False if profile not found.
    """
    from .models import UserProfile
    from .gist_storage import save_profiles_to_gist

    profile = UserProfile.objects.filter(user_id=user_id).first()
    if not profile:
        return False

    profile.activity_level = activity_level
    profile.goal = goal
    profile.save()

    save_profiles_to_gist()
    return True
