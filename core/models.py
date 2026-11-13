import secrets
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone


def generate_invitation_token():
    return secrets.token_urlsafe(32)


class User(AbstractUser):
    class AccountType(models.TextChoices):
        ADULT = "adult", "Adult"
        STUDENT = "student", "Student"
        PLATFORM_ADMIN = "platform_admin", "Platform administrator"

    account_type = models.CharField(
        max_length=24, choices=AccountType.choices, default=AccountType.ADULT
    )
    display_name = models.CharField(max_length=120, blank=True)
    must_change_password = models.BooleanField(default=False)
    email_verified = models.BooleanField(default=False)

    def __str__(self):
        return self.display_name or self.username


class Institution(models.Model):
    class Kind(models.TextChoices):
        SCHOOL = "school", "School"
        ORGANIZATION = "organization", "Educational organization"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        SUSPENDED = "suspended", "Suspended"

    name = models.CharField(max_length=180)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.SCHOOL)
    slug = models.SlugField(max_length=200, unique=True)
    contact_email = models.EmailField()
    country_or_region = models.CharField(max_length=100, blank=True)
    description = models.CharField(max_length=500, blank=True)
    logo = models.ImageField(upload_to="institution-logos/", blank=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    application_notes = models.TextField(blank=True)
    require_content_approval = models.BooleanField(default=True)
    terms_accepted_at = models.DateTimeField(null=True, blank=True)
    terms_version = models.CharField(max_length=40, blank=True)
    approved_by = models.ForeignKey(
        "User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_institutions",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class Membership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Institution owner"
        ADMIN = "admin", "Institution administrator"
        TEACHER = "teacher", "Teacher"
        REVIEWER = "reviewer", "Content reviewer"
        STUDENT = "student", "Student"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INVITED = "invited", "Invited"
        SUSPENDED = "suspended", "Suspended"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    institution = models.ForeignKey(
        Institution, on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.CharField(max_length=20, choices=Role.choices)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.ACTIVE
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "institution"],
                name="unique_user_institution_membership",
            )
        ]
        indexes = [models.Index(fields=["institution", "role", "status"])]

    def __str__(self):
        return f"{self.user} — {self.institution} ({self.role})"


class AcademicYear(models.Model):
    institution = models.ForeignKey(
        Institution, on_delete=models.CASCADE, related_name="academic_years"
    )
    name = models.CharField(max_length=80)
    starts_on = models.DateField(null=True, blank=True)
    ends_on = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["institution", "name"],
                name="unique_academic_year_per_institution",
            )
        ]
        ordering = ["-is_active", "-starts_on", "name"]

    def __str__(self):
        return f"{self.institution.name} — {self.name}"


class Classroom(models.Model):
    institution = models.ForeignKey(
        Institution, on_delete=models.CASCADE, related_name="classrooms"
    )
    academic_year = models.ForeignKey(
        AcademicYear,
        on_delete=models.PROTECT,
        related_name="classrooms",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=100, help_text="For example: Grade 4 - Blue")
    grade_level = models.CharField(max_length=50, help_text="For example: Grade 4")
    section = models.CharField(max_length=50, blank=True)
    age_min = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(3), MaxValueValidator(21)]
    )
    age_max = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(3), MaxValueValidator(21)]
    )
    teachers = models.ManyToManyField(
        User, blank=True, related_name="teaching_classrooms"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["institution", "academic_year", "name"],
                name="unique_class_name_per_year",
            )
        ]
        ordering = ["grade_level", "name"]

    def __str__(self):
        return f"{self.institution.name} / {self.name}"


class StudentProfile(models.Model):
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="student_profile"
    )
    institution = models.ForeignKey(
        Institution, on_delete=models.PROTECT, related_name="students"
    )
    classroom = models.ForeignKey(
        Classroom,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="students",
    )
    student_code = models.CharField(max_length=40, blank=True)
    preferred_language = models.CharField(max_length=10, default="en")
    avatar = models.CharField(max_length=40, default="star")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["institution", "classroom", "is_active"])]

    def __str__(self):
        return self.user.display_name or self.user.username


class GuardianLink(models.Model):
    guardian = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="guardian_links"
    )
    student = models.ForeignKey(
        StudentProfile, on_delete=models.CASCADE, related_name="guardian_links"
    )
    relationship = models.CharField(max_length=40, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    consent_recorded_at = models.DateTimeField(null=True, blank=True)
    consent_policy_version = models.CharField(max_length=40, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    verification_token = models.CharField(
        max_length=64, unique=True, default=generate_invitation_token, editable=False
    )
    verification_expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["guardian", "student"], name="unique_guardian_student_link"
            )
        ]

    @property
    def is_verified(self):
        return self.verified_at is not None and self.revoked_at is None


class Course(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        REVIEW = "review", "In review"
        PUBLISHED = "published", "Published"
        ARCHIVED = "archived", "Archived"

    institution = models.ForeignKey(
        Institution, on_delete=models.CASCADE, related_name="courses"
    )
    created_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="created_courses"
    )
    title = models.CharField(max_length=180)
    summary = models.CharField(max_length=500)
    subject = models.CharField(max_length=100)
    language = models.CharField(max_length=12, default="en")
    grade_levels = models.JSONField(
        default=list, blank=True, help_text="Grade labels this course is suitable for"
    )
    learning_objectives = models.JSONField(default=list, blank=True)
    estimated_minutes = models.PositiveSmallIntegerField(default=20)
    emoji = models.CharField(max_length=12, default="📘", blank=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT
    )
    published_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["subject", "title"]
        indexes = [models.Index(fields=["institution", "status"])]

    def __str__(self):
        return self.title


class Lesson(models.Model):
    class ContentType(models.TextChoices):
        TEXT = "text", "Reading"
        VIDEO = "video", "Video"
        AUDIO = "audio", "Audio"
        ACTIVITY = "activity", "Activity"
        QUIZ = "quiz", "Quiz"

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="lessons")
    title = models.CharField(max_length=180)
    content_type = models.CharField(
        max_length=16, choices=ContentType.choices, default=ContentType.TEXT
    )
    body = models.TextField(blank=True)
    media_url = models.URLField(
        blank=True,
        help_text="Optional trusted media URL; avoid public/private child data in URLs.",
    )
    duration_minutes = models.PositiveSmallIntegerField(default=5)
    order = models.PositiveSmallIntegerField(default=1)
    is_required = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["course", "order"], name="unique_lesson_order_per_course"
            )
        ]

    def __str__(self):
        return f"{self.course.title}: {self.title}"


class QuizQuestion(models.Model):
    lesson = models.ForeignKey(
        Lesson, on_delete=models.CASCADE, related_name="questions"
    )
    prompt = models.CharField(max_length=500)
    choices = models.JSONField(
        default=list,
        help_text="List of strings; correct choice index is never exposed before submission.",
    )
    correct_index = models.PositiveSmallIntegerField(default=0)
    explanation = models.CharField(max_length=500, blank=True)
    points = models.PositiveSmallIntegerField(default=1)
    order = models.PositiveSmallIntegerField(default=1)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.prompt[:80]


class CourseAssignment(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        REVOKED = "revoked", "Revoked"

    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name="assignments"
    )
    institution = models.ForeignKey(
        Institution, on_delete=models.CASCADE, related_name="course_assignments"
    )
    classroom = models.ForeignKey(
        Classroom,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="course_assignments",
    )
    student = models.ForeignKey(
        StudentProfile,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="individual_assignments",
    )
    assigned_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="created_assignments"
    )
    starts_at = models.DateTimeField(null=True, blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.ACTIVE
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["institution", "status", "classroom"])]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(classroom__isnull=True) ^ models.Q(student__isnull=True)
                ),
                name="assignment_exactly_one_target",
            ),
            models.UniqueConstraint(
                fields=["course", "classroom"],
                condition=models.Q(classroom__isnull=False),
                name="unique_course_class_assignment",
            ),
            models.UniqueConstraint(
                fields=["course", "student"],
                condition=models.Q(student__isnull=False),
                name="unique_course_student_assignment",
            ),
        ]

    def clean(self):
        from django.core.exceptions import ValidationError

        if bool(self.classroom_id) == bool(self.student_id):
            raise ValidationError("Choose exactly one target: classroom or student.")
        if self.classroom_id and self.classroom.institution_id != self.institution_id:
            raise ValidationError("Classroom must belong to the same institution.")
        if self.student_id and self.student.institution_id != self.institution_id:
            raise ValidationError("Student must belong to the same institution.")
        if self.course_id and self.course.institution_id != self.institution_id:
            raise ValidationError("Course must belong to the same institution.")

    def __str__(self):
        return f"{self.course} assignment"


class LearningProgress(models.Model):
    class Status(models.TextChoices):
        NOT_STARTED = "not_started", "Not started"
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"

    student = models.ForeignKey(
        StudentProfile, on_delete=models.CASCADE, related_name="progress_records"
    )
    lesson = models.ForeignKey(
        Lesson, on_delete=models.CASCADE, related_name="progress_records"
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.NOT_STARTED
    )
    percent = models.PositiveSmallIntegerField(
        default=0, validators=[MaxValueValidator(100)]
    )
    last_position = models.PositiveIntegerField(default=0)
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["student", "lesson"], name="unique_student_lesson_progress"
            )
        ]
        indexes = [models.Index(fields=["student", "status"])]


class QuizAttempt(models.Model):
    student = models.ForeignKey(
        StudentProfile, on_delete=models.CASCADE, related_name="quiz_attempts"
    )
    lesson = models.ForeignKey(
        Lesson, on_delete=models.CASCADE, related_name="quiz_attempts"
    )
    answers = models.JSONField(default=dict)
    score = models.PositiveSmallIntegerField(default=0)
    max_score = models.PositiveSmallIntegerField(default=0)
    submitted_at = models.DateTimeField(auto_now_add=True)


class RewardEvent(models.Model):
    student = models.ForeignKey(
        StudentProfile, on_delete=models.CASCADE, related_name="reward_events"
    )
    event_key = models.CharField(max_length=100)
    points = models.PositiveSmallIntegerField(default=0)
    reason = models.CharField(max_length=180)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["student", "event_key"], name="unique_reward_event_per_student"
            )
        ]


class Invitation(models.Model):
    class Role(models.TextChoices):
        ADMIN = "admin", "Institution administrator"
        TEACHER = "teacher", "Teacher"
        REVIEWER = "reviewer", "Content reviewer"

    institution = models.ForeignKey(
        Institution, on_delete=models.CASCADE, related_name="invitations"
    )
    email = models.EmailField()
    role = models.CharField(max_length=16, choices=Role.choices)
    token = models.CharField(
        max_length=64, unique=True, default=generate_invitation_token, editable=False
    )
    invited_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="sent_invitations"
    )
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def is_valid(self):
        return (
            self.accepted_at is None
            and self.expires_at > timezone.now()
            and self.institution.status == Institution.Status.APPROVED
        )


class AuditEvent(models.Model):
    actor = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_events",
    )
    institution = models.ForeignKey(
        Institution,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_events",
    )
    action = models.CharField(max_length=100)
    object_type = models.CharField(max_length=80, blank=True)
    object_id = models.CharField(max_length=80, blank=True)
    outcome = models.CharField(max_length=20, default="success")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["institution", "created_at"]),
            models.Index(fields=["actor", "created_at"]),
        ]


class EmailVerification(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="email_verifications"
    )
    token = models.CharField(
        max_length=64, unique=True, default=generate_invitation_token, editable=False
    )
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def is_valid(self):
        return self.used_at is None and self.expires_at > timezone.now()


class SafetyReport(models.Model):
    class Category(models.TextChoices):
        INAPPROPRIATE = "inappropriate", "Inappropriate content"
        INCORRECT = "incorrect", "Incorrect or confusing information"
        BROKEN = "broken", "Broken link or technical issue"
        PRIVACY = "privacy", "Privacy or personal information concern"
        OTHER = "other", "Other safety concern"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        REVIEWING = "reviewing", "Reviewing"
        RESOLVED = "resolved", "Resolved"
        DISMISSED = "dismissed", "Dismissed"

    institution = models.ForeignKey(
        Institution, on_delete=models.CASCADE, related_name="safety_reports"
    )
    reporter = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="safety_reports",
    )
    course = models.ForeignKey(
        Course,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="safety_reports",
    )
    lesson = models.ForeignKey(
        Lesson,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="safety_reports",
    )
    category = models.CharField(max_length=20, choices=Category.choices)
    details = models.TextField(max_length=1500, blank=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.OPEN
    )
    reviewed_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reviewed_safety_reports",
    )
    resolution_notes = models.CharField(max_length=1000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["status", "-created_at"]
        indexes = [models.Index(fields=["institution", "status", "created_at"])]


class Announcement(models.Model):
    """An institution or teacher-authored message delivered to a defined learning audience."""

    institution = models.ForeignKey(
        Institution, on_delete=models.CASCADE, related_name="announcements"
    )
    author = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="announcements"
    )
    title = models.CharField(max_length=180)
    body = models.TextField(max_length=5000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class AnnouncementRecipient(models.Model):
    """Per-user delivery and read state; a unique row prevents duplicate notifications."""

    announcement = models.ForeignKey(
        Announcement, on_delete=models.CASCADE, related_name="deliveries"
    )
    recipient = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="announcement_deliveries"
    )
    viewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["announcement", "recipient"],
                name="unique_announcement_recipient",
            )
        ]
        indexes = [models.Index(fields=["recipient", "viewed_at"])]


class AnnouncementComment(models.Model):
    """Teacher-only replies/comments on an announcement thread."""

    announcement = models.ForeignKey(
        Announcement, on_delete=models.CASCADE, related_name="comments"
    )
    author = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="announcement_comments"
    )
    body = models.TextField(max_length=3000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
