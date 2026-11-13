"""Shared navigation context for notification badge state."""

from .models import AnnouncementRecipient


def notification_count(request):
    if not request.user.is_authenticated:
        return {"unread_notifications": 0}
    return {
        "unread_notifications": AnnouncementRecipient.objects.filter(
            recipient=request.user, viewed_at__isnull=True
        ).count()
    }
