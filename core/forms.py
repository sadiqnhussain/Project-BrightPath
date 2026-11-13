from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.utils.text import slugify
from django.utils import timezone
from urllib.parse import urlparse
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.db import transaction
from .models import (
    Institution,
    Classroom,
    StudentProfile,
    Course,
    Lesson,
    CourseAssignment,
    GuardianLink,
    QuizQuestion,
    Invitation,
    SafetyReport,
    AcademicYear,
    Membership,
)

User = get_user_model()


class InstitutionApplicationForm(forms.ModelForm):
    admin_username = forms.CharField(
        max_length=150,
        label="Your username",
        validators=User._meta.get_field("username").validators,
    )
    admin_display_name = forms.CharField(max_length=120, label="Your full name")
    admin_password = forms.CharField(
        widget=forms.PasswordInput, min_length=12, label="Password (12+ characters)"
    )

    def clean_admin_password(self):
        value = self.cleaned_data["admin_password"]
        validate_password(value)
        return value

    confirm_terms = forms.BooleanField(
        label="I confirm I am authorized to apply for this institution and agree to the platform safety and privacy terms.",
        help_text='Please read the <a href="/privacy/" target="_blank" rel="noopener noreferrer">privacy overview</a> and <a href="/safety/" target="_blank" rel="noopener noreferrer">child safety principles</a>.',
    )

    class Meta:
        model = Institution
        fields = ["name", "kind", "contact_email", "country_or_region", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def clean_contact_email(self):
        value = self.cleaned_data["contact_email"].strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise forms.ValidationError(
                "An account already uses this email. Use a separate institution contact email."
            )
        return value

    def clean_admin_username(self):
        v = self.cleaned_data["admin_username"].strip()
        if User.objects.filter(username__iexact=v).exists():
            raise forms.ValidationError("That username is already in use.")
        return v

    @transaction.atomic
    def save(self, commit=True):
        institution = super().save(commit=False)
        base = slugify(institution.name)[:150] or "learning-space"
        slug = base
        n = 2
        while Institution.objects.filter(slug=slug).exists():
            slug = f"{base}-{n}"
            n += 1
        institution.slug = slug
        institution.terms_accepted_at = timezone.now()
        institution.terms_version = "institution-terms-v1"
        if commit:
            institution.save()
            user = User.objects.create_user(
                username=self.cleaned_data["admin_username"],
                email=institution.contact_email,
                password=self.cleaned_data["admin_password"],
                account_type=User.AccountType.ADULT,
                display_name=self.cleaned_data["admin_display_name"],
            )
            from .models import Membership, AuditEvent

            Membership.objects.create(
                user=user, institution=institution, role=Membership.Role.OWNER
            )
            AuditEvent.objects.create(
                actor=user,
                institution=institution,
                action="institution.application_submitted",
                object_type="Institution",
                object_id=str(institution.pk),
            )
        return institution


class ClassroomForm(forms.ModelForm):
    teachers = forms.ModelMultipleChoiceField(
        queryset=User.objects.none(),
        required=False,
        help_text="Only teachers from this institution can be assigned.",
    )

    class Meta:
        model = Classroom
        fields = [
            "name",
            "grade_level",
            "section",
            "academic_year",
            "teachers",
            "age_min",
            "age_max",
            "is_active",
        ]
        widgets = {
            "age_min": forms.NumberInput(attrs={"min": 3, "max": 21}),
            "age_max": forms.NumberInput(attrs={"min": 3, "max": 21}),
        }

    def clean(self):
        data = super().clean()
        if (
            data.get("age_min")
            and data.get("age_max")
            and data["age_max"] < data["age_min"]
        ):
            self.add_error("age_max", "Maximum age must be at least the minimum age.")
        return data

    def __init__(self, *args, institution=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["academic_year"].queryset = (
            AcademicYear.objects.filter(institution=institution)
            if institution
            else AcademicYear.objects.none()
        )
        teacher_ids = (
            Membership.objects.filter(
                institution=institution,
                role=Membership.Role.TEACHER,
                status=Membership.Status.ACTIVE,
            ).values_list("user_id", flat=True)
            if institution
            else []
        )
        self.fields["teachers"].queryset = User.objects.filter(id__in=teacher_ids)


class AcademicYearForm(forms.ModelForm):
    class Meta:
        model = AcademicYear
        fields = ["name", "starts_on", "ends_on", "is_active"]
        widgets = {
            "starts_on": forms.DateInput(attrs={"type": "date"}),
            "ends_on": forms.DateInput(attrs={"type": "date"}),
        }

    def clean(self):
        data = super().clean()
        if (
            data.get("starts_on")
            and data.get("ends_on")
            and data["ends_on"] < data["starts_on"]
        ):
            self.add_error("ends_on", "End date must be on or after the start date.")
        return data


class StudentCreateForm(forms.Form):
    display_name = forms.CharField(max_length=120)
    username = forms.CharField(
        max_length=150,
        help_text="A unique school login; avoid using a child’s email address.",
        validators=User._meta.get_field("username").validators,
    )
    student_code = forms.CharField(max_length=40, required=False)
    classroom = forms.ModelChoiceField(queryset=Classroom.objects.none())
    temporary_password = forms.CharField(
        widget=forms.PasswordInput,
        min_length=12,
        help_text="Give this privately to the guardian/student and require a change at first login.",
    )

    def clean_temporary_password(self):
        value = self.cleaned_data["temporary_password"]
        validate_password(value)
        return value

    def __init__(self, *args, institution=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.institution = institution
        self.fields["classroom"].queryset = (
            Classroom.objects.filter(institution=institution, is_active=True)
            if institution
            else Classroom.objects.none()
        )

    def clean_username(self):
        value = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=value).exists():
            raise forms.ValidationError("This username is already in use.")
        return value

    @transaction.atomic
    def save(self, institution):
        user = User.objects.create_user(
            username=self.cleaned_data["username"],
            password=self.cleaned_data["temporary_password"],
            account_type=User.AccountType.STUDENT,
            display_name=self.cleaned_data["display_name"],
            must_change_password=True,
        )
        from .models import Membership

        Membership.objects.create(
            user=user, institution=institution, role=Membership.Role.STUDENT
        )
        profile = StudentProfile.objects.create(
            user=user,
            institution=institution,
            classroom=self.cleaned_data["classroom"],
            student_code=self.cleaned_data["student_code"],
        )
        return profile


class CourseForm(forms.ModelForm):
    grade_levels = forms.CharField(
        help_text="Comma-separated, for example Grade 1, Grade 2."
    )
    learning_objectives = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={"rows": 2, "placeholder": "One objective per line"}
        ),
    )

    class Meta:
        model = Course
        fields = [
            "title",
            "summary",
            "subject",
            "language",
            "grade_levels",
            "learning_objectives",
            "estimated_minutes",
            "emoji",
        ]
        widgets = {"summary": forms.Textarea(attrs={"rows": 3})}

    def clean_grade_levels(self):
        v = self.cleaned_data.get("grade_levels")
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v

    def clean_learning_objectives(self):
        v = self.cleaned_data.get("learning_objectives")
        if isinstance(v, str):
            return [x.strip() for x in v.splitlines() if x.strip()]
        return v


class LessonForm(forms.ModelForm):
    def clean_media_url(self):
        value = self.cleaned_data.get("media_url", "").strip()
        if value:
            parsed = urlparse(value)
            allowed = {
                "youtube.com",
                "www.youtube.com",
                "youtu.be",
                "vimeo.com",
                "player.vimeo.com",
            }
            if parsed.scheme != "https" or parsed.hostname not in allowed:
                raise forms.ValidationError(
                    "Use an HTTPS link from an approved media provider (YouTube or Vimeo). Review the media before sharing it with children."
                )
        return value

    class Meta:
        model = Lesson
        fields = [
            "title",
            "content_type",
            "body",
            "media_url",
            "duration_minutes",
            "order",
            "is_required",
        ]
        widgets = {
            "body": forms.Textarea(attrs={"rows": 8}),
            "media_url": forms.URLInput(
                attrs={"placeholder": "https://... (optional)"}
            ),
        }


class AssignmentForm(forms.ModelForm):
    classroom = forms.ModelChoiceField(
        queryset=Classroom.objects.none(),
        required=False,
        help_text="Choose a class OR a single student, not both.",
    )
    student = forms.ModelChoiceField(
        queryset=StudentProfile.objects.none(),
        required=False,
        help_text="Choose a student OR a class, not both.",
    )

    class Meta:
        model = CourseAssignment
        fields = ["course", "classroom", "student", "starts_at", "due_at"]
        widgets = {
            "starts_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "due_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def __init__(self, *args, institution=None, teacher_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.institution = institution
        self.fields["course"].queryset = (
            Course.objects.filter(
                institution=institution, status=Course.Status.PUBLISHED
            )
            if institution
            else Course.objects.none()
        )
        self.fields["classroom"].queryset = (
            Classroom.objects.filter(institution=institution, is_active=True)
            if institution
            else Classroom.objects.none()
        )
        self.fields["student"].queryset = (
            StudentProfile.objects.filter(institution=institution, is_active=True)
            if institution
            else StudentProfile.objects.none()
        )
        if institution and teacher_user:
            teacher = teacher_user
            self.fields["classroom"].queryset = self.fields[
                "classroom"
            ].queryset.filter(teachers=teacher)
            self.fields["student"].queryset = self.fields["student"].queryset.filter(
                classroom__teachers=teacher
            )
            self.fields["course"].queryset = self.fields["course"].queryset.filter(
                created_by=teacher
            )

    def clean(self):
        data = super().clean()
        if bool(data.get("classroom")) == bool(data.get("student")):
            raise forms.ValidationError(
                "Choose exactly one target: an entire class or one student."
            )
        return data


class QuizQuestionForm(forms.ModelForm):
    choices_text = forms.CharField(
        widget=forms.Textarea(
            attrs={"rows": 4, "placeholder": "One answer choice per line"}
        ),
        help_text="Enter 2–6 choices, one per line.",
    )

    class Meta:
        model = QuizQuestion
        fields = ["prompt", "correct_index", "explanation", "points", "order"]

    def clean_choices_text(self):
        choices = [
            x.strip()
            for x in self.cleaned_data["choices_text"].splitlines()
            if x.strip()
        ]
        if len(choices) < 2 or len(choices) > 6:
            raise forms.ValidationError("Provide between 2 and 6 choices.")
        return choices

    def clean(self):
        data = super().clean()
        choices = data.get("choices_text", [])
        idx = data.get("correct_index")
        if idx is not None and choices and idx >= len(choices):
            self.add_error(
                "correct_index",
                "Correct choice index must match an available choice. Use 0 for the first choice.",
            )
        return data


class GuardianSignupForm(forms.Form):
    display_name = forms.CharField(max_length=120)
    username = forms.CharField(
        max_length=150, validators=User._meta.get_field("username").validators
    )
    email = forms.EmailField()
    password = forms.CharField(widget=forms.PasswordInput, min_length=12)

    def clean_password(self):
        value = self.cleaned_data["password"]
        validate_password(value)
        return value

    def clean_username(self):
        value = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=value).exists():
            raise forms.ValidationError("That username is already in use.")
        return value

    def clean_email(self):
        value = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise forms.ValidationError(
                "An account with this email already exists. Sign in instead."
            )
        return value

    def save(self):
        user = User.objects.create_user(
            username=self.cleaned_data["username"],
            email=self.cleaned_data["email"],
            password=self.cleaned_data["password"],
            display_name=self.cleaned_data["display_name"],
            account_type=User.AccountType.ADULT,
        )
        return user


class StaffInvitationForm(forms.Form):
    email = forms.EmailField()
    role = forms.ChoiceField(choices=Invitation.Role.choices)

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()


class InvitationAcceptForm(forms.Form):
    display_name = forms.CharField(max_length=120)
    username = forms.CharField(
        max_length=150, validators=User._meta.get_field("username").validators
    )
    password = forms.CharField(widget=forms.PasswordInput, min_length=12)

    def clean_password(self):
        value = self.cleaned_data["password"]
        validate_password(value)
        return value

    def clean_username(self):
        value = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=value).exists():
            raise forms.ValidationError("That username is already in use.")
        return value


class SafetyReportForm(forms.ModelForm):
    class Meta:
        model = SafetyReport
        fields = ["category", "details"]
        widgets = {
            "details": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "Tell the school what seems wrong. Do not include private information about yourself or another child.",
                }
            )
        }
