import json
import secrets
from datetime import timedelta
from django.contrib import messages
from django.contrib.auth import login, logout, authenticate, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.decorators.cache import never_cache
from django.utils.text import slugify
from django.core.mail import send_mail
from django.urls import reverse
from django.conf import settings
from .forms import (
    InstitutionApplicationForm,
    ClassroomForm,
    AcademicYearForm,
    StudentCreateForm,
    CourseForm,
    LessonForm,
    AssignmentForm,
    QuizQuestionForm,
    GuardianSignupForm,
    StaffInvitationForm,
    InvitationAcceptForm,
    SafetyReportForm,
)
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
    EmailVerification,
    SafetyReport,
    Announcement,
    AnnouncementRecipient,
    AnnouncementComment,
)


def audit(request, action, institution=None, obj=None, outcome="success", details=None):
    try:
        ip = request.META.get("REMOTE_ADDR")
        AuditEvent.objects.create(
            actor=request.user if request.user.is_authenticated else None,
            institution=institution,
            action=action,
            object_type=obj.__class__.__name__ if obj else "",
            object_id=str(obj.pk) if obj else "",
            outcome=outcome,
            ip_address=ip,
            details=details or {},
        )
    except Exception:
        # Audit failures should be surfaced in monitoring in production; do not leak internals to a child UI.
        pass


def membership_for(user, institution=None):
    qs = Membership.objects.filter(
        user=user,
        status=Membership.Status.ACTIVE,
        institution__status=Institution.Status.APPROVED,
    )
    if institution:
        qs = qs.filter(institution=institution)
    return qs.select_related("institution").first()


def require_roles(user, roles, institution=None):
    m = membership_for(user, institution)
    if not m or m.role not in roles:
        raise PermissionDenied("You do not have permission to perform this action.")
    return m


def student_profile(user):
    try:
        return user.student_profile
    except StudentProfile.DoesNotExist:
        raise PermissionDenied("This account does not have an active student profile.")


def course_is_assigned(profile, course):
    if (
        not profile.is_active
        or not profile.user.is_active
        or profile.institution.status != Institution.Status.APPROVED
    ):
        return False
    if (
        course.institution_id != profile.institution_id
        or course.status != Course.Status.PUBLISHED
    ):
        return False
    now = timezone.now()
    target_q = Q(student=profile)
    if profile.classroom_id:
        target_q |= Q(classroom_id=profile.classroom_id)
    assignments = CourseAssignment.objects.filter(
        course=course,
        institution=profile.institution,
        status=CourseAssignment.Status.ACTIVE,
    ).filter(target_q)
    assignments = assignments.filter(
        Q(starts_at__isnull=True) | Q(starts_at__lte=now)
    ).filter(Q(due_at__isnull=True) | Q(due_at__gte=now))
    if not assignments.exists():
        return False
    grades = course.grade_levels or []
    if grades and profile.classroom and profile.classroom.grade_level not in grades:
        return False
    return True


def home(request):
    return render(request, "core/home.html")


def privacy_page(request):
    return render(request, "core/privacy.html")


def safety_page(request):
    return render(request, "core/safety.html")


@never_cache
def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.get_user()
        if not user.is_active:
            messages.error(
                request,
                "This account is not active. Please contact your school administrator or guardian.",
            )
        else:
            login(request, user)
            audit(request, "auth.login")
            return redirect(
                "change_password" if user.must_change_password else "dashboard"
            )
    return render(request, "core/login.html", {"form": form})


@login_required
@require_POST
def logout_view(request):
    audit(request, "auth.logout")
    logout(request)
    return redirect("home")


@login_required
@never_cache
def change_password(request):
    form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        user.must_change_password = False
        user.save(update_fields=["must_change_password"])
        update_session_auth_hash(request, user)
        messages.success(request, "Your password has been updated.")
        return redirect("dashboard")
    return render(request, "core/change_password.html", {"form": form})


def institution_apply(request):
    if request.method == "POST":
        form = InstitutionApplicationForm(request.POST)
        if form.is_valid():
            inst = form.save()
            messages.success(
                request,
                "Your application has been received. The platform team must review it before the learning space becomes active.",
            )
            return render(
                request, "core/application_submitted.html", {"institution": inst}
            )
    else:
        form = InstitutionApplicationForm()
    return render(request, "core/institution_apply.html", {"form": form})


@login_required
@never_cache
def dashboard(request):
    if (
        request.user.is_superuser
        or request.user.account_type == User.AccountType.PLATFORM_ADMIN
    ):
        pending = Institution.objects.filter(status=Institution.Status.PENDING).count()
        return render(
            request,
            "core/platform_dashboard.html",
            {
                "pending_count": pending,
                "institutions": Institution.objects.order_by("-created_at")[:8],
            },
        )
    if request.user.account_type == User.AccountType.STUDENT:
        return redirect("student_home")
    memberships = Membership.objects.filter(
        user=request.user,
        status=Membership.Status.ACTIVE,
        institution__status=Institution.Status.APPROVED,
    ).select_related("institution")
    if memberships.count() == 0:
        guardian_links = GuardianLink.objects.filter(
            guardian=request.user
        ).select_related("student__user", "student__institution")
        if guardian_links.exists():
            return redirect("guardian_dashboard")
        pending_memberships = Membership.objects.filter(
            user=request.user,
            status=Membership.Status.ACTIVE,
            institution__status=Institution.Status.PENDING,
        ).select_related("institution")
        if pending_memberships.exists():
            return render(
                request,
                "core/pending_institution.html",
                {"institutions": [m.institution for m in pending_memberships]},
            )
        return render(request, "core/no_membership.html")
    if memberships.count() > 1 and not request.GET.get("institution"):
        return render(
            request, "core/select_institution.html", {"memberships": memberships}
        )
    m = (
        memberships.filter(institution_id=request.GET.get("institution")).first()
        if request.GET.get("institution")
        else memberships.first()
    )
    if not m:
        raise PermissionDenied
    request.session["active_institution_id"] = m.institution_id
    inst = m.institution
    if m.role in [Membership.Role.OWNER, Membership.Role.ADMIN]:
        context = {
            "membership": m,
            "institution": inst,
            "class_count": Classroom.objects.filter(
                institution=inst, is_active=True
            ).count(),
            "student_count": StudentProfile.objects.filter(
                institution=inst, is_active=True
            ).count(),
            "course_count": Course.objects.filter(institution=inst).count(),
            "published_count": Course.objects.filter(
                institution=inst, status=Course.Status.PUBLISHED
            ).count(),
            "recent_courses": Course.objects.filter(institution=inst).order_by(
                "-updated_at"
            )[:5],
        }
        return render(request, "core/institution_dashboard.html", context)
    if m.role in [Membership.Role.TEACHER, Membership.Role.REVIEWER]:
        return render(
            request,
            "core/teacher_dashboard.html",
            {
                "membership": m,
                "institution": inst,
                "courses": Course.objects.filter(
                    institution=inst, created_by=request.user
                ).order_by("-updated_at")[:8],
                "classrooms": Classroom.objects.filter(
                    institution=inst, teachers=request.user, is_active=True
                ),
            },
        )
    raise PermissionDenied


@login_required
def platform_institutions(request):
    if not (
        request.user.is_superuser
        or request.user.account_type == User.AccountType.PLATFORM_ADMIN
    ):
        raise PermissionDenied
    status = request.GET.get("status", "pending")
    institutions = Institution.objects.filter(status=status).order_by("created_at")
    return render(
        request,
        "core/platform_institutions.html",
        {"institutions": institutions, "status": status},
    )


@login_required
@require_POST
def institution_decision(request, pk, decision):
    if not (
        request.user.is_superuser
        or request.user.account_type == User.AccountType.PLATFORM_ADMIN
    ):
        raise PermissionDenied
    inst = get_object_or_404(Institution, pk=pk)
    if decision == "approve":
        inst.status = Institution.Status.APPROVED
        inst.approved_by = request.user
        inst.approved_at = timezone.now()
        inst.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
        audit(request, "institution.approved", inst, inst)
        messages.success(request, f"{inst.name} has been approved.")
    elif decision == "reject":
        inst.status = Institution.Status.REJECTED
        inst.save(update_fields=["status", "updated_at"])
        audit(request, "institution.rejected", inst, inst)
        messages.success(request, f"{inst.name} has been rejected.")
    elif decision == "suspend":
        inst.status = Institution.Status.SUSPENDED
        inst.save(update_fields=["status", "updated_at"])
        audit(request, "institution.suspended", inst, inst)
        messages.success(request, f"{inst.name} has been suspended.")
    else:
        raise Http404
    return redirect("platform_institutions")


def current_institution(request, roles=None):
    qs = Membership.objects.filter(
        user=request.user,
        status=Membership.Status.ACTIVE,
        institution__status=Institution.Status.APPROVED,
    ).select_related("institution")
    selected = request.GET.get("institution") or request.session.get(
        "active_institution_id"
    )
    if selected:
        m = qs.filter(institution_id=selected).first()
        if not m:
            raise PermissionDenied("You do not have access to that learning space.")
    else:
        if qs.count() > 1:
            raise PermissionDenied("Choose a learning space from your dashboard first.")
        m = qs.first()
    if not m:
        raise PermissionDenied("No active institution membership was found.")
    request.session["active_institution_id"] = m.institution_id
    if roles and m.role not in roles:
        raise PermissionDenied("You do not have permission to perform this action.")
    return m.institution, m


@login_required
def academic_years(request):
    inst, m = current_institution(
        request, [Membership.Role.OWNER, Membership.Role.ADMIN]
    )
    form = AcademicYearForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if AcademicYear.objects.filter(
            institution=inst, name=form.cleaned_data["name"]
        ).exists():
            form.add_error(
                "name", "This academic year already exists for the institution."
            )
        else:
            year = form.save(commit=False)
            year.institution = inst
            with transaction.atomic():
                if year.is_active:
                    AcademicYear.objects.filter(
                        institution=inst, is_active=True
                    ).update(is_active=False)
                year.save()
            audit(request, "academic_year.created", inst, year)
            messages.success(request, "Academic year saved.")
            return redirect("academic_years")
    years = AcademicYear.objects.filter(institution=inst).order_by(
        "-is_active", "-starts_on", "name"
    )
    return render(
        request,
        "core/academic_years.html",
        {"institution": inst, "form": form, "years": years},
    )


@login_required
def classroom_list(request):
    inst, m = current_institution(
        request, [Membership.Role.OWNER, Membership.Role.ADMIN, Membership.Role.TEACHER]
    )
    qs = Classroom.objects.filter(institution=inst)
    if m.role == Membership.Role.TEACHER:
        qs = qs.filter(teachers=request.user)
    qs = qs.annotate(student_count=Count("students")).order_by("grade_level", "name")
    return render(
        request,
        "core/classroom_list.html",
        {
            "institution": inst,
            "classrooms": qs,
            "can_manage": m.role in [Membership.Role.OWNER, Membership.Role.ADMIN],
        },
    )


@login_required
def classroom_create(request):
    inst, m = current_institution(
        request, [Membership.Role.OWNER, Membership.Role.ADMIN]
    )
    form = ClassroomForm(request.POST or None, institution=inst)
    if request.method == "POST" and form.is_valid():
        c = form.save(commit=False)
        c.institution = inst
        if c.academic_year and c.academic_year.institution_id != inst.id:
            raise PermissionDenied
        duplicate = Classroom.objects.filter(
            institution=inst, academic_year=c.academic_year, name=c.name
        ).exists()
        if duplicate:
            form.add_error(
                "name", "A class with this name already exists for that academic year."
            )
        else:
            c.save()
            form.save_m2m()
            audit(request, "classroom.created", inst, c)
            messages.success(request, "Class created.")
            return redirect("classroom_list")
    return render(
        request,
        "core/form_page.html",
        {
            "institution": inst,
            "form": form,
            "title": "Create a class",
            "subtitle": "Organize students by grade, year and section.",
        },
    )


@login_required
def student_create(request):
    inst, m = current_institution(
        request, [Membership.Role.OWNER, Membership.Role.ADMIN]
    )
    form = StudentCreateForm(request.POST or None, institution=inst)
    if request.method == "POST" and form.is_valid():
        profile = form.save(inst)
        audit(request, "student.created", inst, profile)
        messages.success(
            request,
            "Student account created. Share the temporary password privately with the guardian/student. They must change it at first sign-in.",
        )
        return redirect("student_list")
    return render(
        request,
        "core/form_page.html",
        {
            "institution": inst,
            "form": form,
            "title": "Add a student",
            "subtitle": "Use a school login rather than collecting a child’s personal email.",
        },
    )


@login_required
def student_list(request):
    inst, m = current_institution(
        request, [Membership.Role.OWNER, Membership.Role.ADMIN, Membership.Role.TEACHER]
    )
    qs = (
        StudentProfile.objects.filter(institution=inst)
        .select_related("user", "classroom")
        .order_by("classroom__grade_level", "user__display_name")
    )
    if m.role == Membership.Role.TEACHER:
        qs = qs.filter(classroom__teachers=request.user)
    return render(
        request,
        "core/student_list.html",
        {
            "institution": inst,
            "students": qs,
            "classrooms": Classroom.objects.filter(institution=inst, is_active=True),
            "can_manage": m.role in [Membership.Role.OWNER, Membership.Role.ADMIN],
        },
    )


@login_required
@require_POST
def student_class_update(request, pk):
    inst, m = current_institution(
        request, [Membership.Role.OWNER, Membership.Role.ADMIN]
    )
    profile = get_object_or_404(StudentProfile, pk=pk, institution=inst)
    class_id = request.POST.get("classroom_id", "").strip()
    if class_id:
        classroom = get_object_or_404(
            Classroom, pk=class_id, institution=inst, is_active=True
        )
        profile.classroom = classroom
    else:
        profile.classroom = None
    profile.save(update_fields=["classroom"])
    audit(
        request,
        "student.class_changed",
        inst,
        profile,
        details={"classroom_id": profile.classroom_id},
    )
    messages.success(request, "Student class placement updated.")
    return redirect("student_list")


@login_required
def course_list(request):
    inst, m = current_institution(
        request,
        [
            Membership.Role.OWNER,
            Membership.Role.ADMIN,
            Membership.Role.TEACHER,
            Membership.Role.REVIEWER,
        ],
    )
    courses = (
        Course.objects.filter(institution=inst)
        .select_related("created_by")
        .order_by("-updated_at")
    )
    return render(
        request,
        "core/course_list.html",
        {
            "institution": inst,
            "courses": courses,
            "can_create": m.role
            in [Membership.Role.OWNER, Membership.Role.ADMIN, Membership.Role.TEACHER],
        },
    )


@login_required
def course_create(request):
    inst, m = current_institution(
        request, [Membership.Role.OWNER, Membership.Role.ADMIN, Membership.Role.TEACHER]
    )
    form = CourseForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        c = form.save(commit=False)
        c.institution = inst
        c.created_by = request.user
        c.status = Course.Status.DRAFT
        c.grade_levels = form.cleaned_data["grade_levels"]
        c.learning_objectives = form.cleaned_data["learning_objectives"]
        c.save()
        audit(request, "course.created", inst, c)
        messages.success(
            request,
            "Course draft created. Add lessons, preview it, then publish when ready.",
        )
        return redirect("course_detail", pk=c.pk)
    return render(
        request,
        "core/form_page.html",
        {
            "institution": inst,
            "form": form,
            "title": "Create a course",
            "subtitle": "Courses are private to your institution until assigned; publishing does not make them public.",
        },
    )


@login_required
def course_edit(request, pk):
    inst, m = current_institution(
        request, [Membership.Role.OWNER, Membership.Role.ADMIN, Membership.Role.TEACHER]
    )
    course = get_object_or_404(Course, pk=pk, institution=inst)
    if m.role == Membership.Role.TEACHER and course.created_by_id != request.user.id:
        raise PermissionDenied
    if course.status == Course.Status.PUBLISHED:
        messages.error(
            request,
            "Published courses are versioned and cannot be edited in place. Create a new course version instead.",
        )
        return redirect("course_detail", pk=pk)
    initial = {
        "grade_levels": ", ".join(course.grade_levels or []),
        "learning_objectives": "\n".join(course.learning_objectives or []),
    }
    form = CourseForm(request.POST or None, instance=course, initial=initial)
    if request.method == "POST" and form.is_valid():
        updated = form.save(commit=False)
        updated.grade_levels = form.cleaned_data["grade_levels"]
        updated.learning_objectives = form.cleaned_data["learning_objectives"]
        if updated.status == Course.Status.REVIEW:
            updated.status = Course.Status.DRAFT
        updated.save()
        audit(request, "course.updated", inst, updated)
        messages.success(
            request, "Course draft updated. Submit it for review again when ready."
        )
        return redirect("course_detail", pk=updated.pk)
    return render(
        request,
        "core/form_page.html",
        {
            "institution": inst,
            "form": form,
            "title": f"Edit course · {course.title}",
            "subtitle": "Changes to a course in review return it to draft. Published courses require a new version.",
        },
    )


@login_required
def course_detail(request, pk):
    inst, m = current_institution(
        request,
        [
            Membership.Role.OWNER,
            Membership.Role.ADMIN,
            Membership.Role.TEACHER,
            Membership.Role.REVIEWER,
        ],
    )
    course = get_object_or_404(Course, pk=pk, institution=inst)
    lessons = course.lessons.prefetch_related("questions")
    can_edit = m.role in [Membership.Role.OWNER, Membership.Role.ADMIN] or (
        m.role == Membership.Role.TEACHER and course.created_by_id == request.user.id
    )
    can_review = m.role in [
        Membership.Role.OWNER,
        Membership.Role.ADMIN,
        Membership.Role.REVIEWER,
    ]
    return render(
        request,
        "core/course_detail.html",
        {
            "institution": inst,
            "course": course,
            "lessons": lessons,
            "can_edit": can_edit,
            "can_review": can_review,
        },
    )


@login_required
def lesson_create(request, course_pk):
    inst, m = current_institution(
        request, [Membership.Role.OWNER, Membership.Role.ADMIN, Membership.Role.TEACHER]
    )
    course = get_object_or_404(Course, pk=course_pk, institution=inst)
    if m.role == Membership.Role.TEACHER and course.created_by_id != request.user.id:
        raise PermissionDenied
    form = LessonForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        lesson = form.save(commit=False)
        lesson.course = course
        if Lesson.objects.filter(course=course, order=lesson.order).exists():
            form.add_error("order", "That lesson order is already used in this course.")
        else:
            lesson.save()
            audit(request, "lesson.created", inst, lesson)
            messages.success(request, "Lesson added.")
            return redirect("course_detail", pk=course.pk)
    return render(
        request,
        "core/form_page.html",
        {
            "institution": inst,
            "form": form,
            "title": f"Add lesson · {course.title}",
            "subtitle": "Keep lessons short, accessible and appropriate for the selected grade.",
        },
    )


@login_required
@require_POST
def course_publish(request, pk):
    inst, m = current_institution(
        request, [Membership.Role.OWNER, Membership.Role.ADMIN, Membership.Role.TEACHER]
    )
    course = get_object_or_404(Course, pk=pk, institution=inst)
    if m.role == Membership.Role.TEACHER and course.created_by_id != request.user.id:
        raise PermissionDenied
    if not course.lessons.exists():
        messages.error(request, "Add at least one lesson before publishing.")
    elif not course.grade_levels:
        messages.error(request, "Select at least one eligible grade before publishing.")
    else:
        if m.role == Membership.Role.TEACHER and inst.require_content_approval:
            course.status = Course.Status.REVIEW
            course.published_at = None
            course.save(update_fields=["status", "published_at", "updated_at"])
            audit(request, "course.submitted_for_review", inst, course)
            messages.success(
                request,
                "Course submitted for school review. Students cannot see it until an authorized school administrator approves it.",
            )
        else:
            course.status = Course.Status.PUBLISHED
            course.published_at = timezone.now()
            course.version += 1
            course.save(
                update_fields=["status", "published_at", "version", "updated_at"]
            )
            audit(request, "course.published", inst, course)
            messages.success(
                request,
                "Course published. It will appear only to students with matching active assignments.",
            )
    return redirect("course_detail", pk=pk)


@login_required
@require_POST
def course_review_decision(request, pk, decision):
    inst, m = current_institution(
        request,
        [Membership.Role.OWNER, Membership.Role.ADMIN, Membership.Role.REVIEWER],
    )
    course = get_object_or_404(
        Course, pk=pk, institution=inst, status=Course.Status.REVIEW
    )
    if decision == "approve":
        course.status = Course.Status.PUBLISHED
        course.published_at = timezone.now()
        course.version += 1
        course.save(update_fields=["status", "published_at", "version", "updated_at"])
        audit(request, "course.review_approved", inst, course)
        messages.success(request, "Course approved and published.")
    elif decision == "return":
        course.status = Course.Status.DRAFT
        course.published_at = None
        course.save(update_fields=["status", "published_at", "updated_at"])
        audit(request, "course.review_returned", inst, course)
        messages.success(request, "Course returned to draft for changes.")
    else:
        raise Http404
    return redirect("course_detail", pk=pk)


@login_required
def safety_report_create(request, course_pk, lesson_pk=None):
    if request.user.account_type == "student":
        profile = student_profile(request.user)
        inst = profile.institution
        course = get_object_or_404(Course, pk=course_pk)
        if not course_is_assigned(profile, course):
            raise PermissionDenied
    else:
        inst, m = current_institution(request)
        course = get_object_or_404(Course, pk=course_pk, institution=inst)
    lesson = (
        get_object_or_404(Lesson, pk=lesson_pk, course=course) if lesson_pk else None
    )
    form = SafetyReportForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        report = form.save(commit=False)
        report.institution = inst
        report.reporter = request.user
        report.course = course
        report.lesson = lesson
        report.save()
        audit(request, "safety_report.created", inst, report)
        messages.success(
            request,
            "Thank you for speaking up. Your report has been sent to the school review team.",
        )
        return (
            redirect("student_course", pk=course.pk)
            if request.user.account_type == "student"
            else redirect("dashboard")
        )
    return render(
        request,
        "core/safety_report_form.html",
        {"form": form, "course": course, "lesson": lesson},
    )


@login_required
def safety_report_list(request):
    if (
        request.user.is_superuser
        or request.user.account_type == User.AccountType.PLATFORM_ADMIN
    ):
        reports = SafetyReport.objects.select_related(
            "institution", "reporter", "course", "lesson"
        ).order_by("status", "-created_at")[:300]
        return render(
            request,
            "core/safety_report_list.html",
            {
                "reports": reports,
                "platform_view": True,
                "status_choices": SafetyReport.Status.choices,
            },
        )
    inst, m = current_institution(
        request,
        [Membership.Role.OWNER, Membership.Role.ADMIN, Membership.Role.REVIEWER],
    )
    reports = (
        SafetyReport.objects.filter(institution=inst)
        .select_related("reporter", "course", "lesson")
        .order_by("status", "-created_at")[:300]
    )
    return render(
        request,
        "core/safety_report_list.html",
        {
            "reports": reports,
            "institution": inst,
            "status_choices": SafetyReport.Status.choices,
        },
    )


@login_required
@require_POST
def safety_report_update(request, pk):
    if (
        request.user.is_superuser
        or request.user.account_type == User.AccountType.PLATFORM_ADMIN
    ):
        report = get_object_or_404(SafetyReport, pk=pk)
        inst = report.institution
    else:
        inst, m = current_institution(
            request,
            [Membership.Role.OWNER, Membership.Role.ADMIN, Membership.Role.REVIEWER],
        )
        report = get_object_or_404(SafetyReport, pk=pk, institution=inst)
    status_value = request.POST.get("status")
    if status_value not in SafetyReport.Status.values:
        raise Http404
    report.status = status_value
    report.resolution_notes = request.POST.get("resolution_notes", "")[:1000]
    report.reviewed_by = request.user
    report.save(
        update_fields=["status", "resolution_notes", "reviewed_by", "updated_at"]
    )
    audit(
        request, "safety_report.updated", inst, report, details={"status": status_value}
    )
    messages.success(request, "Report status updated.")
    return redirect("safety_report_list")


@login_required
def institution_reports(request):
    inst, m = current_institution(
        request, [Membership.Role.OWNER, Membership.Role.ADMIN, Membership.Role.TEACHER]
    )
    students = (
        StudentProfile.objects.filter(
            institution=inst, is_active=True, user__is_active=True
        )
        .select_related("user", "classroom")
        .order_by("classroom__grade_level", "user__display_name")
    )
    if m.role == Membership.Role.TEACHER:
        students = students.filter(classroom__teachers=request.user)
    rows = []
    for profile in students[:1000]:
        target_q = Q(student=profile)
        if profile.classroom_id:
            target_q |= Q(classroom_id=profile.classroom_id)
        assigned = CourseAssignment.objects.filter(
            institution=inst, status=CourseAssignment.Status.ACTIVE
        ).filter(target_q)
        now = timezone.now()
        assigned = assigned.filter(
            Q(starts_at__isnull=True) | Q(starts_at__lte=now)
        ).filter(Q(due_at__isnull=True) | Q(due_at__gte=now))
        courses = Course.objects.filter(
            id__in=assigned.values_list("course_id", flat=True),
            status=Course.Status.PUBLISHED,
            institution=inst,
        )
        eligible = [c for c in courses if course_is_assigned(profile, c)]
        lesson_ids = []
        for course in eligible:
            lesson_ids.extend(
                course.lessons.filter(is_required=True).values_list("id", flat=True)
            )
        completed = (
            LearningProgress.objects.filter(
                student=profile,
                lesson_id__in=lesson_ids,
                status=LearningProgress.Status.COMPLETED,
            ).count()
            if lesson_ids
            else 0
        )
        attempts = QuizAttempt.objects.filter(
            student=profile, lesson__course__in=eligible
        )
        attempt_list = list(attempts.values_list("score", "max_score"))
        scored = [
            (score / max_score * 100) for score, max_score in attempt_list if max_score
        ]
        latest = (
            LearningProgress.objects.filter(student=profile)
            .order_by("-updated_at")
            .values_list("updated_at", flat=True)
            .first()
        )
        rows.append(
            {
                "student": profile,
                "course_count": len(eligible),
                "required_lessons": len(lesson_ids),
                "completed": completed,
                "percent": (
                    round(completed * 100 / len(lesson_ids)) if lesson_ids else 0
                ),
                "quiz_average": round(sum(scored) / len(scored)) if scored else None,
                "has_quiz_average": bool(scored),
                "last_activity": latest,
            }
        )
    return render(
        request,
        "core/institution_reports.html",
        {
            "institution": inst,
            "rows": rows,
            "is_admin": m.role in [Membership.Role.OWNER, Membership.Role.ADMIN],
        },
    )


@login_required
def assignment_create(request):
    inst, m = current_institution(
        request, [Membership.Role.OWNER, Membership.Role.ADMIN, Membership.Role.TEACHER]
    )
    form = AssignmentForm(
        request.POST or None,
        institution=inst,
        teacher_user=request.user if m.role == Membership.Role.TEACHER else None,
    )
    if request.method == "POST" and form.is_valid():
        assignment = form.save(commit=False)
        assignment.institution = inst
        assignment.assigned_by = request.user
        try:
            assignment.full_clean()
        except ValidationError as e:
            form.add_error(None, e)
        else:
            duplicate = CourseAssignment.objects.filter(
                course=assignment.course,
                classroom=assignment.classroom,
                student=assignment.student,
            ).exists()
            if duplicate:
                form.add_error(
                    None,
                    "This course already has an assignment for that target. Contact an administrator if access needs to be restored.",
                )
            else:
                assignment.save()
                audit(request, "course.assigned", inst, assignment)
                messages.success(
                    request,
                    "Course assigned. Eligible students will see it in their learning space.",
                )
                return redirect("assignment_list")
    return render(
        request,
        "core/form_page.html",
        {
            "institution": inst,
            "form": form,
            "title": "Assign a course",
            "subtitle": "Assign a published course to one class or one student. Access is checked by the server.",
        },
    )


@login_required
def assignment_list(request):
    inst, m = current_institution(
        request, [Membership.Role.OWNER, Membership.Role.ADMIN, Membership.Role.TEACHER]
    )
    assignments = CourseAssignment.objects.filter(institution=inst)
    if m.role == Membership.Role.TEACHER:
        assignments = assignments.filter(course__created_by=request.user).filter(
            Q(classroom__teachers=request.user)
            | Q(student__classroom__teachers=request.user)
        )
    assignments = assignments.select_related(
        "course", "classroom", "student__user", "assigned_by"
    ).order_by("-created_at")
    return render(
        request,
        "core/assignment_list.html",
        {"institution": inst, "assignments": assignments},
    )


@login_required
@never_cache
def student_home(request):
    if request.user.account_type != User.AccountType.STUDENT:
        raise PermissionDenied
    profile = student_profile(request.user)
    if (
        not profile.is_active
        or not profile.user.is_active
        or profile.institution.status != Institution.Status.APPROVED
    ):
        raise PermissionDenied
    target_q = Q(student=profile)
    if profile.classroom_id:
        target_q |= Q(classroom_id=profile.classroom_id)
    assigned_ids = (
        CourseAssignment.objects.filter(
            institution=profile.institution, status="active"
        )
        .filter(target_q)
        .filter(Q(starts_at__isnull=True) | Q(starts_at__lte=timezone.now()))
        .filter(Q(due_at__isnull=True) | Q(due_at__gte=timezone.now()))
        .values_list("course_id", flat=True)
    )
    courses = Course.objects.filter(
        id__in=assigned_ids,
        institution=profile.institution,
        status=Course.Status.PUBLISHED,
    )
    if profile.classroom:
        courses = (
            courses.filter(
                Q(grade_levels=[])
                | Q(grade_levels__contains=[profile.classroom.grade_level])
            )
            if not _is_sqlite()
            else courses
        )
    course_data = []
    for c in courses.distinct().order_by("subject", "title"):
        if course_is_assigned(profile, c):
            total = c.lessons.count()
            completed = LearningProgress.objects.filter(
                student=profile,
                lesson__course=c,
                status=LearningProgress.Status.COMPLETED,
            ).count()
            course_data.append(
                {
                    "course": c,
                    "total": total,
                    "completed": completed,
                    "percent": int(completed * 100 / total) if total else 0,
                }
            )
    points = sum(x.points for x in profile.reward_events.all())
    return render(
        request,
        "core/student_home.html",
        {
            "profile": profile,
            "course_data": course_data,
            "points": points,
            "completed_count": LearningProgress.objects.filter(
                student=profile, status="completed"
            ).count(),
        },
    )


def _is_sqlite():
    from django.db import connection

    return connection.vendor == "sqlite"


@login_required
@never_cache
def student_course(request, pk):
    profile = student_profile(request.user)
    course = get_object_or_404(Course, pk=pk)
    if not course_is_assigned(profile, course):
        raise PermissionDenied
    lessons = course.lessons.all()
    progress = {
        p.lesson_id: p
        for p in LearningProgress.objects.filter(student=profile, lesson__course=course)
    }
    lesson_rows = [
        {"lesson": lesson, "progress": progress.get(lesson.pk)} for lesson in lessons
    ]
    return render(
        request,
        "core/student_course.html",
        {"profile": profile, "course": course, "lessons": lesson_rows},
    )


@login_required
@never_cache
def student_lesson(request, pk):
    profile = student_profile(request.user)
    lesson = get_object_or_404(Lesson, pk=pk)
    if not course_is_assigned(profile, lesson.course):
        raise PermissionDenied
    questions = lesson.questions.all()
    if request.method == "POST":
        action = request.POST.get("action", "complete")
        if action == "quiz":
            submitted = {}
            score = max_score = 0
            for q in questions:
                raw = request.POST.get(f"q_{q.pk}")
                try:
                    idx = int(raw)
                except (ValueError, TypeError):
                    idx = -1
                submitted[str(q.pk)] = idx
                max_score += q.points
                if idx == q.correct_index:
                    score += q.points
            with transaction.atomic():
                attempt = QuizAttempt.objects.create(
                    student=profile,
                    lesson=lesson,
                    answers=submitted,
                    score=score,
                    max_score=max_score,
                )
                # Reward once per lesson completion, server-side and idempotent.
                RewardEvent.objects.get_or_create(
                    student=profile,
                    event_key=f"quiz-complete-{lesson.pk}",
                    defaults={"points": 5, "reason": "Completed a learning activity"},
                )
                LearningProgress.objects.update_or_create(
                    student=profile,
                    lesson=lesson,
                    defaults={
                        "status": LearningProgress.Status.COMPLETED,
                        "percent": 100,
                        "completed_at": timezone.now(),
                    },
                )
            audit(
                request,
                "quiz.submitted",
                profile.institution,
                attempt,
                details={"score": score, "max_score": max_score},
            )
            feedback_rows = [
                {
                    "question": q,
                    "correct": submitted.get(str(q.pk)) == q.correct_index,
                    "selected": submitted.get(str(q.pk)),
                    "correct_choice": (
                        q.choices[q.correct_index]
                        if 0 <= q.correct_index < len(q.choices)
                        else ""
                    ),
                }
                for q in questions
            ]
            return render(
                request,
                "core/quiz_result.html",
                {
                    "profile": profile,
                    "lesson": lesson,
                    "score": score,
                    "max_score": max_score,
                    "feedback_rows": feedback_rows,
                },
            )
        LearningProgress.objects.update_or_create(
            student=profile,
            lesson=lesson,
            defaults={
                "status": LearningProgress.Status.COMPLETED,
                "percent": 100,
                "completed_at": timezone.now(),
            },
        )
        RewardEvent.objects.get_or_create(
            student=profile,
            event_key=f"lesson-complete-{lesson.pk}",
            defaults={"points": 2, "reason": "Completed a lesson"},
        )
        audit(request, "lesson.completed", profile.institution, lesson)
        messages.success(request, "Nice work! Your progress has been saved.")
        next_lesson = lesson.course.lessons.filter(order__gt=lesson.order).first()
        return (
            redirect("student_lesson", pk=next_lesson.pk)
            if next_lesson
            else redirect("student_course", pk=lesson.course.pk)
        )
    progress, _ = LearningProgress.objects.get_or_create(
        student=profile,
        lesson=lesson,
        defaults={"status": LearningProgress.Status.IN_PROGRESS},
    )
    if progress.status == LearningProgress.Status.NOT_STARTED:
        progress.status = LearningProgress.Status.IN_PROGRESS
        progress.save(update_fields=["status", "updated_at"])
    return render(
        request,
        "core/student_lesson.html",
        {"profile": profile, "lesson": lesson, "questions": questions},
    )


@login_required
@never_cache
def guardian_dashboard(request):
    if request.user.account_type != User.AccountType.ADULT:
        raise PermissionDenied
    all_links = GuardianLink.objects.filter(
        guardian=request.user,
        revoked_at__isnull=True,
        student__institution__status=Institution.Status.APPROVED,
        student__is_active=True,
        student__user__is_active=True,
    ).select_related("student__user", "student__institution", "student__classroom")
    links = all_links.filter(verified_at__isnull=False, revoked_at__isnull=True)
    if not all_links.exists():
        raise PermissionDenied("No guardian-child link is available.")
    summaries = []
    for link in links:
        p = link.student
        summaries.append(
            {
                "link": link,
                "progress_count": LearningProgress.objects.filter(
                    student=p, status="completed"
                ).count(),
                "points": sum(r.points for r in p.reward_events.all()),
                "recent": LearningProgress.objects.filter(student=p)
                .select_related("lesson", "lesson__course")
                .order_by("-updated_at")[:5],
            }
        )
    return render(
        request,
        "core/guardian_dashboard.html",
        {
            "summaries": summaries,
            "pending_links": all_links.filter(verified_at__isnull=True),
        },
    )


@login_required
def guardian_link_create(request):
    inst, m = current_institution(
        request, [Membership.Role.OWNER, Membership.Role.ADMIN]
    )
    if request.method == "POST":
        email = request.POST.get("guardian_email", "").strip().lower()
        student_id = request.POST.get("student_id")
        student = get_object_or_404(StudentProfile, pk=student_id, institution=inst)
        guardians = User.objects.filter(
            email__iexact=email,
            account_type=User.AccountType.ADULT,
            email_verified=True,
        )
        if guardians.count() != 1:
            messages.error(
                request,
                "No unique verified guardian account was found for that email. Ask the guardian to verify their account and confirm the email address.",
            )
            return redirect("student_list")
        guardian = guardians.first()
        if not guardian.email_verified:
            messages.error(
                request,
                "This guardian must verify their email address before the school can request a child link.",
            )
            return redirect("student_list")
        with transaction.atomic():
            link, created = GuardianLink.objects.get_or_create(
                guardian=guardian,
                student=student,
                defaults={
                    "relationship": request.POST.get("relationship", ""),
                    "verification_expires_at": timezone.now() + timedelta(days=14),
                },
            )
            if not created and (
                link.revoked_at
                or (
                    link.verified_at is None
                    and link.verification_expires_at
                    and link.verification_expires_at < timezone.now()
                )
            ):
                link.verification_token = secrets.token_urlsafe(32)
                link.verification_expires_at = timezone.now() + timedelta(days=14)
                link.revoked_at = None
                link.verified_at = None
                link.consent_recorded_at = None
                link.consent_policy_version = ""
                link.relationship = request.POST.get("relationship", "")
                link.save()
                created = True
            if created:
                signin_url = request.build_absolute_uri(reverse("login"))
                send_mail(
                    f"Guardian connection requested by {inst.name}",
                    f"{inst.name} has requested to connect your guardian account to a student learning profile. Sign in to BrightPath to review the request and explicitly consent before any learning summary is shared: {signin_url}\n\nIf you do not recognize this request, do not accept it and contact the school.",
                    settings.DEFAULT_FROM_EMAIL,
                    [guardian.email],
                    fail_silently=False,
                )
        if created:
            messages.success(
                request,
                "Guardian link request sent. Learning summaries remain private until the guardian signs in and explicitly consents.",
            )
            audit(request, "guardian.link_created", inst, link)
        else:
            messages.info(request, "That guardian link already exists.")
        return redirect("student_list")
    return redirect("student_list")


def guardian_signup(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = GuardianSignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = form.save()
            verification = EmailVerification.objects.create(
                user=user, expires_at=timezone.now() + timedelta(hours=24)
            )
            verify_url = request.build_absolute_uri(
                reverse("verify_email", args=[verification.token])
            )
            send_mail(
                "Verify your BrightPath guardian account",
                f"Hello {user.display_name},\n\nVerify your email within 24 hours: {verify_url}\n\nIf you did not create this account, you can ignore this message.",
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                fail_silently=False,
            )
        audit(request, "guardian.account_created")
        messages.success(
            request,
            "Account created. Check your email for a verification link. You must verify your email before the school can link a child to your account.",
        )
        return redirect("login")
    return render(request, "core/guardian_signup.html", {"form": form})


def verify_email(request, token):
    verification = get_object_or_404(
        EmailVerification.objects.select_related("user"), token=token
    )
    if not verification.is_valid:
        messages.error(
            request,
            "This email verification link has expired or has already been used.",
        )
    else:
        verification.user.email_verified = True
        verification.user.save(update_fields=["email_verified"])
        verification.used_at = timezone.now()
        verification.save(update_fields=["used_at"])
        audit(request, "account.email_verified")
        messages.success(
            request,
            "Email verified. You can now sign in; your school can request a guardian link.",
        )
    return redirect("login")


@login_required
@require_POST
def guardian_consent(request, token):
    link = get_object_or_404(
        GuardianLink,
        verification_token=token,
        guardian=request.user,
        revoked_at__isnull=True,
    )
    if request.user.account_type != User.AccountType.ADULT:
        raise PermissionDenied
    if (
        link.student.institution.status != Institution.Status.APPROVED
        or not link.student.is_active
        or not link.student.user.is_active
    ):
        messages.error(
            request,
            "This student learning space is not currently active. Contact the school for help.",
        )
        return redirect("dashboard")
    if link.verified_at:
        messages.info(request, "This guardian link is already active.")
    elif link.verification_expires_at and link.verification_expires_at < timezone.now():
        messages.error(
            request,
            "This request has expired. Please contact the school to send a new request.",
        )
    elif request.POST.get("consent") != "yes":
        messages.error(
            request, "You must confirm consent to activate the guardian link."
        )
    else:
        link.verified_at = timezone.now()
        link.consent_recorded_at = timezone.now()
        link.consent_policy_version = "guardian-consent-v1"
        link.save(
            update_fields=[
                "verified_at",
                "consent_recorded_at",
                "consent_policy_version",
            ]
        )
        audit(request, "guardian.consent_accepted", link.student.institution, link)
        messages.success(
            request,
            "Guardian link confirmed. You can now view the approved learning summary.",
        )
    return redirect("guardian_dashboard")


@login_required
@require_POST
def guardian_revoke_link(request, pk):
    if request.user.account_type != User.AccountType.ADULT:
        raise PermissionDenied
    link = get_object_or_404(
        GuardianLink,
        pk=pk,
        guardian=request.user,
        verified_at__isnull=False,
        revoked_at__isnull=True,
    )
    link.revoked_at = timezone.now()
    link.verification_token = secrets.token_urlsafe(32)
    link.verification_expires_at = timezone.now()
    link.save(
        update_fields=["revoked_at", "verification_token", "verification_expires_at"]
    )
    audit(request, "guardian.consent_revoked", link.student.institution, link)
    messages.success(
        request,
        "Learning summary sharing has been stopped. The school will need a new consent request to restore access.",
    )
    return redirect("guardian_dashboard")


@login_required
def quiz_question_create(request, lesson_pk):
    inst, m = current_institution(
        request, [Membership.Role.OWNER, Membership.Role.ADMIN, Membership.Role.TEACHER]
    )
    lesson = get_object_or_404(Lesson, pk=lesson_pk, course__institution=inst)
    if (
        m.role == Membership.Role.TEACHER
        and lesson.course.created_by_id != request.user.id
    ):
        raise PermissionDenied
    form = QuizQuestionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        q = form.save(commit=False)
        q.lesson = lesson
        q.choices = form.cleaned_data["choices_text"]
        q.save()
        audit(request, "quiz_question.created", inst, q)
        messages.success(
            request,
            "Question added. Correct answers remain private to staff and the server.",
        )
        return redirect("course_detail", pk=lesson.course_id)
    return render(
        request,
        "core/form_page.html",
        {
            "institution": inst,
            "form": form,
            "title": f"Add question · {lesson.title}",
            "subtitle": "Correct choice index starts at 0: first choice = 0, second = 1, and so on.",
        },
    )


@login_required
def staff_invitation_create(request):
    inst, m = current_institution(
        request, [Membership.Role.OWNER, Membership.Role.ADMIN]
    )
    form = StaffInvitationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"]
        role = form.cleaned_data["role"]
        existing = Invitation.objects.filter(
            institution=inst,
            email__iexact=email,
            accepted_at__isnull=True,
            expires_at__gt=timezone.now(),
        ).exists()
        existing_user = User.objects.filter(email__iexact=email).first()
        active_member = (
            Membership.objects.filter(
                user=existing_user, institution=inst, status=Membership.Status.ACTIVE
            ).exists()
            if existing_user
            else False
        )
        if active_member:
            form.add_error(
                "email", "This person is already an active member of the institution."
            )
        elif existing:
            form.add_error(
                "email", "An active invitation already exists for this email."
            )
        else:
            with transaction.atomic():
                invitation = Invitation.objects.create(
                    institution=inst,
                    email=email,
                    role=role,
                    invited_by=request.user,
                    expires_at=timezone.now() + timedelta(days=7),
                )
                invite_url = request.build_absolute_uri(
                    reverse("invitation_accept", args=[invitation.token])
                )
                send_mail(
                    f"Invitation to {inst.name} on BrightPath",
                    f"You have been invited to join {inst.name} as {invitation.get_role_display()}. Accept within 7 days: {invite_url}\n\nIf you were not expecting this, ignore this email.",
                    settings.DEFAULT_FROM_EMAIL,
                    [email],
                    fail_silently=False,
                )
            audit(request, "staff.invitation_created", inst, invitation)
            messages.success(
                request,
                "Invitation sent. In local development, the email is printed in the runserver console.",
            )
            return redirect("staff_invitation_create")
    active = Invitation.objects.filter(institution=inst).order_by("-created_at")[:30]
    members = list(
        Membership.objects.filter(institution=inst, status=Membership.Status.ACTIVE)
        .exclude(role=Membership.Role.STUDENT)
        .select_related("user")
        .order_by("role", "user__display_name")
    )
    can_deactivate_ids = [
        member.pk
        for member in members
        if member.user_id != request.user.id
        and member.role != Membership.Role.OWNER
        and (
            m.role == Membership.Role.OWNER
            or member.role in [Membership.Role.TEACHER, Membership.Role.REVIEWER]
        )
    ]
    return render(
        request,
        "core/staff_invitations.html",
        {
            "institution": inst,
            "form": form,
            "invitations": active,
            "members": members,
            "now": timezone.now(),
            "can_deactivate_ids": can_deactivate_ids,
        },
    )


@login_required
@require_POST
def staff_membership_deactivate(request, pk):
    inst, m = current_institution(
        request, [Membership.Role.OWNER, Membership.Role.ADMIN]
    )
    target = get_object_or_404(
        Membership, pk=pk, institution=inst, status=Membership.Status.ACTIVE
    )
    if target.user_id == request.user.id or target.role == Membership.Role.OWNER:
        raise PermissionDenied(
            "Owners and your own membership cannot be removed from this screen."
        )
    if m.role == Membership.Role.ADMIN and target.role not in [
        Membership.Role.TEACHER,
        Membership.Role.REVIEWER,
    ]:
        raise PermissionDenied(
            "Administrators can only deactivate teachers or reviewers."
        )
    target.status = Membership.Status.SUSPENDED
    target.save(update_fields=["status"])
    audit(
        request,
        "staff.membership_suspended",
        inst,
        target,
        details={"role": target.role},
    )
    messages.success(request, "Staff access has been deactivated for this institution.")
    return redirect("staff_invitation_create")


def invitation_accept(request, token):
    invitation = get_object_or_404(
        Invitation.objects.select_related("institution"), token=token
    )
    if not invitation.is_valid:
        return render(
            request, "core/invitation_expired.html", {"invitation": invitation}
        )
    if invitation.email and request.user.is_authenticated:
        if request.user.email.lower() != invitation.email.lower():
            messages.error(
                request,
                "This invitation belongs to a different email address. Sign out and use the invited account.",
            )
            return redirect("dashboard")
        user = request.user
    elif request.user.is_authenticated:
        user = request.user
    else:
        form = InvitationAcceptForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            if User.objects.filter(email__iexact=invitation.email).exists():
                form.add_error(
                    None,
                    "An account already exists for this email. Sign in with that account to accept the invitation.",
                )
            else:
                user = User.objects.create_user(
                    username=form.cleaned_data["username"],
                    email=invitation.email,
                    display_name=form.cleaned_data["display_name"],
                    password=form.cleaned_data["password"],
                    account_type=User.AccountType.ADULT,
                    email_verified=True,
                )
                login(request, user)
                member, created = Membership.objects.get_or_create(
                    user=user,
                    institution=invitation.institution,
                    defaults={
                        "role": invitation.role,
                        "status": Membership.Status.ACTIVE,
                    },
                )
                if not created:
                    member.role = invitation.role
                    member.status = Membership.Status.ACTIVE
                    member.save(update_fields=["role", "status"])
                invitation.accepted_at = timezone.now()
                invitation.save(update_fields=["accepted_at"])
                audit(
                    request,
                    "staff.invitation_accepted",
                    invitation.institution,
                    invitation,
                )
                messages.success(request, f"Welcome to {invitation.institution.name}.")
                return redirect("dashboard")
        return render(
            request,
            "core/invitation_accept.html",
            {"invitation": invitation, "form": form},
        )
    if (
        user.email.lower() != invitation.email.lower()
        or user.account_type != User.AccountType.ADULT
    ):
        raise PermissionDenied
    if not user.email_verified:
        user.email_verified = True
        user.save(update_fields=["email_verified"])
    member, created = Membership.objects.get_or_create(
        user=user,
        institution=invitation.institution,
        defaults={"role": invitation.role, "status": Membership.Status.ACTIVE},
    )
    if not created:
        member.role = invitation.role
        member.status = Membership.Status.ACTIVE
        member.save(update_fields=["role", "status"])
    invitation.accepted_at = timezone.now()
    invitation.save(update_fields=["accepted_at"])
    audit(request, "staff.invitation_accepted", invitation.institution, invitation)
    messages.success(request, f"Welcome to {invitation.institution.name}.")
    return redirect("dashboard")


@login_required
def teacher_classrooms(request):
    inst, m = current_institution(
        request, [Membership.Role.OWNER, Membership.Role.ADMIN, Membership.Role.TEACHER]
    )
    if m.role == Membership.Role.TEACHER:
        qs = Classroom.objects.filter(
            institution=inst, teachers=request.user, is_active=True
        )
    else:
        qs = Classroom.objects.filter(institution=inst, is_active=True)
    return render(
        request,
        "core/classroom_list.html",
        {
            "institution": inst,
            "classrooms": qs.annotate(student_count=Count("students")),
            "can_manage": m.role in [Membership.Role.OWNER, Membership.Role.ADMIN],
        },
    )


def health(request):
    return JsonResponse({"status": "ok", "service": "kids-learning-platform"})


@login_required
@never_cache
def notifications(request):
    """Display a user's delivered announcements and mark opened messages as read."""
    deliveries = (
        AnnouncementRecipient.objects.filter(recipient=request.user)
        .select_related(
            "announcement", "announcement__author", "announcement__institution"
        )
        .prefetch_related("announcement__comments__author")
    )
    if request.method == "POST":
        delivery_id = request.POST.get("delivery_id")
        delivery = get_object_or_404(
            AnnouncementRecipient, pk=delivery_id, recipient=request.user
        )
        membership = membership_for(request.user, delivery.announcement.institution)
        if membership and membership.role in [
            Membership.Role.OWNER,
            Membership.Role.ADMIN,
            Membership.Role.TEACHER,
            Membership.Role.REVIEWER,
        ]:
            body = request.POST.get("body", "").strip()
            if body:
                AnnouncementComment.objects.create(
                    announcement=delivery.announcement,
                    author=request.user,
                    body=body[:3000],
                )
                messages.success(request, "Your comment was added.")
        else:
            messages.error(
                request, "Only institution staff can comment on announcements."
            )
        return redirect("notifications")
    unseen = deliveries.filter(viewed_at__isnull=True)
    unseen.update(viewed_at=timezone.now())
    for delivery in deliveries:
        role_membership = membership_for(
            request.user, delivery.announcement.institution
        )
        delivery.can_comment = bool(
            role_membership
            and role_membership.role
            in [
                Membership.Role.OWNER,
                Membership.Role.ADMIN,
                Membership.Role.TEACHER,
                Membership.Role.REVIEWER,
            ]
        )
    return render(
        request,
        "core/notifications.html",
        {
            "deliveries": deliveries,
            "unread_count": unseen.count(),
            "memberships": Membership.objects.filter(
                user=request.user,
                status=Membership.Status.ACTIVE,
                institution__status=Institution.Status.APPROVED,
            ).select_related("institution"),
            "courses": Course.objects.filter(
                institution__memberships__user=request.user,
                institution__memberships__role=Membership.Role.TEACHER,
                institution__memberships__status=Membership.Status.ACTIVE,
            ).distinct(),
            "staff_targets": Membership.objects.filter(
                institution__memberships__user=request.user,
                institution__memberships__role__in=[
                    Membership.Role.OWNER,
                    Membership.Role.ADMIN,
                ],
                institution__memberships__status=Membership.Status.ACTIVE,
                status=Membership.Status.ACTIVE,
            ).select_related("user", "institution"),
        },
    )


@login_required
@require_POST
def announcement_create(request):
    """Create an announcement with role-specific audience validation."""
    inst_id = request.POST.get("institution_id")
    membership = (
        membership_for(request.user, get_object_or_404(Institution, pk=inst_id))
        if inst_id
        else membership_for(request.user)
    )
    if not membership:
        raise PermissionDenied("An active institution membership is required.")
    institution = membership.institution
    role = membership.role
    title, body = (
        request.POST.get("title", "").strip(),
        request.POST.get("body", "").strip(),
    )
    if not title or not body:
        messages.error(request, "Enter both a title and a message.")
        return redirect("notifications")

    recipients = User.objects.none()
    if role in [Membership.Role.OWNER, Membership.Role.ADMIN]:
        audience = request.POST.get("audience", "")
        memberships = Membership.objects.filter(
            institution=institution, status=Membership.Status.ACTIVE
        )
        if audience == "all":
            memberships = memberships.filter(
                role__in=[Membership.Role.TEACHER, Membership.Role.STUDENT]
            )
        elif audience == "teachers":
            memberships = memberships.filter(role=Membership.Role.TEACHER)
        elif audience == "students":
            memberships = memberships.filter(role=Membership.Role.STUDENT)
        elif audience == "teacher":
            memberships = memberships.filter(
                role=Membership.Role.TEACHER, user_id=request.POST.get("target_id")
            )
        elif audience == "student":
            memberships = memberships.filter(
                role=Membership.Role.STUDENT, user_id=request.POST.get("target_id")
            )
        else:
            messages.error(request, "Choose a valid audience.")
            return redirect("notifications")
        recipients = User.objects.filter(pk__in=memberships.values("user_id"))
    elif role == Membership.Role.TEACHER:
        # Teachers can address enrolled students by course, but cannot select an individual learner.
        course_ids = list(
            Course.objects.filter(
                institution=institution, created_by=request.user
            ).values_list("id", flat=True)
        )
        course_ids += list(
            CourseAssignment.objects.filter(
                institution=institution,
                status=CourseAssignment.Status.ACTIVE,
                classroom__teachers=request.user,
            ).values_list("course_id", flat=True)
        )
        course_ids = sorted(set(course_ids))
        requested = request.POST.get("course_id")
        try:
            requested_id = int(requested) if requested and requested != "all" else None
        except (TypeError, ValueError):
            requested_id = None
        if requested == "all":
            chosen = course_ids
        elif requested_id in course_ids:
            chosen = [requested_id]
        else:
            messages.error(
                request, "Choose one of your assigned courses or all your courses."
            )
            return redirect("notifications")
        profiles = StudentProfile.objects.filter(
            institution=institution, is_active=True
        ).select_related("classroom", "user")
        eligible_ids = [
            profile.user_id
            for profile in profiles
            if any(
                course_is_assigned(profile, course)
                for course in Course.objects.filter(pk__in=chosen)
            )
        ]
        recipients = User.objects.filter(pk__in=eligible_ids)
    else:
        raise PermissionDenied("This role cannot send announcements.")

    announcement = Announcement.objects.create(
        institution=institution,
        author=request.user,
        title=title[:180],
        body=body[:5000],
    )
    AnnouncementRecipient.objects.bulk_create(
        [
            AnnouncementRecipient(announcement=announcement, recipient_id=uid)
            for uid in recipients.values_list("id", flat=True)
        ],
        ignore_conflicts=True,
    )
    audit(
        request,
        "announcement.created",
        institution,
        announcement,
        details={"recipient_count": recipients.count()},
    )
    messages.success(request, "Announcement sent.")
    return redirect("notifications")
