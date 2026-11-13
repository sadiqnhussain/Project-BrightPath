from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import (
    User,
    Institution,
    Membership,
    AcademicYear,
    Classroom,
    StudentProfile,
    GuardianLink,
    Course,
    Lesson,
    QuizQuestion,
    CourseAssignment,
    LearningProgress,
    QuizAttempt,
    RewardEvent,
    Invitation,
    AuditEvent,
    SafetyReport,
    EmailVerification,
)


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        (
            "Platform profile",
            {"fields": ("account_type", "display_name", "must_change_password")},
        ),
    )
    list_display = (
        "username",
        "display_name",
        "email",
        "account_type",
        "is_active",
        "is_staff",
    )
    list_filter = ("account_type", "is_active", "is_staff")


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0


@admin.register(Institution)
class InstitutionAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "status", "contact_email", "created_at")
    list_filter = ("status", "kind")
    search_fields = ("name", "contact_email")
    readonly_fields = ("created_at", "updated_at", "approved_at")
    inlines = [MembershipInline]


@admin.register(Classroom)
class ClassroomAdmin(admin.ModelAdmin):
    list_display = ("name", "institution", "grade_level", "academic_year", "is_active")
    list_filter = ("institution", "is_active")


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "institution",
        "subject",
        "status",
        "version",
        "updated_at",
    )
    list_filter = ("institution", "status", "subject")
    search_fields = ("title", "summary")


@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "institution", "classroom", "is_active")
    list_filter = ("institution", "is_active")
    search_fields = ("user__username", "user__display_name", "student_code")


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor", "institution", "action", "outcome")
    list_filter = ("action", "outcome", "institution")
    readonly_fields = [f.name for f in AuditEvent._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class SensitiveReadOnlyAdmin(admin.ModelAdmin):
    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(GuardianLink, SensitiveReadOnlyAdmin)
admin.site.register(EmailVerification, SensitiveReadOnlyAdmin)
admin.site.register(SafetyReport, SensitiveReadOnlyAdmin)
admin.site.register(
    [
        Membership,
        AcademicYear,
        Lesson,
        QuizQuestion,
        CourseAssignment,
        LearningProgress,
        QuizAttempt,
        RewardEvent,
        Invitation,
    ]
)
