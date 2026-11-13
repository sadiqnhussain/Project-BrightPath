from django.db.models import Q
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import (
    User,
    Institution,
    Membership,
    Classroom,
    StudentProfile,
    Course,
    Lesson,
    CourseAssignment,
    LearningProgress,
    QuizQuestion,
    QuizAttempt,
    RewardEvent,
    GuardianLink,
    AuditEvent,
)
from .views import course_is_assigned, student_profile


class InstitutionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Institution
        fields = ["id", "name", "kind", "slug", "status"]


class ClassroomSerializer(serializers.ModelSerializer):
    class Meta:
        model = Classroom
        fields = ["id", "name", "grade_level", "section", "academic_year", "is_active"]


class LessonSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lesson
        fields = [
            "id",
            "title",
            "content_type",
            "body",
            "media_url",
            "duration_minutes",
            "order",
            "is_required",
        ]


class CourseSerializer(serializers.ModelSerializer):
    lesson_count = serializers.IntegerField(source="lessons.count", read_only=True)

    class Meta:
        model = Course
        fields = [
            "id",
            "title",
            "summary",
            "subject",
            "language",
            "grade_levels",
            "learning_objectives",
            "estimated_minutes",
            "emoji",
            "status",
            "version",
            "lesson_count",
        ]


class ProgressSerializer(serializers.ModelSerializer):
    lesson_title = serializers.CharField(source="lesson.title", read_only=True)
    course_id = serializers.IntegerField(source="lesson.course_id", read_only=True)

    class Meta:
        model = LearningProgress
        fields = [
            "id",
            "lesson",
            "lesson_title",
            "course_id",
            "status",
            "percent",
            "last_position",
            "completed_at",
            "updated_at",
        ]


def membership_for_request(request):
    qs = Membership.objects.filter(
        user=request.user, status="active", institution__status="approved"
    ).select_related("institution")
    selected = request.query_params.get("institution")
    if selected:
        return qs.filter(institution_id=selected).first()
    if qs.count() == 1:
        return qs.first()
    return None


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    user = request.user
    data = {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name or user.username,
        "account_type": user.account_type,
        "must_change_password": user.must_change_password,
    }
    memberships = Membership.objects.filter(user=user, status="active").select_related(
        "institution"
    )
    data["memberships"] = [
        {
            "institution": m.institution.name,
            "institution_id": m.institution_id,
            "role": m.role,
            "status": m.institution.status,
        }
        for m in memberships
    ]
    if user.account_type == "student":
        try:
            p = user.student_profile
            data["student"] = {
                "id": p.id,
                "institution": p.institution.name,
                "classroom": p.classroom.name if p.classroom else None,
                "grade_level": p.classroom.grade_level if p.classroom else None,
                "preferred_language": p.preferred_language,
            }
        except StudentProfile.DoesNotExist:
            data["student"] = None
    return Response(data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def student_courses(request):
    if request.user.account_type != "student":
        return Response({"detail": "Student account required."}, status=403)
    try:
        p = student_profile(request.user)
    except Exception:
        return Response({"detail": "Student profile not available."}, status=403)
    now = timezone.now()
    target_q = Q(student=p)
    if p.classroom_id:
        target_q |= Q(classroom_id=p.classroom_id)
    ids = (
        CourseAssignment.objects.filter(institution=p.institution, status="active")
        .filter(target_q)
        .filter(Q(starts_at__isnull=True) | Q(starts_at__lte=now))
        .filter(Q(due_at__isnull=True) | Q(due_at__gte=now))
        .values_list("course_id", flat=True)
    )
    courses = Course.objects.filter(
        id__in=ids, status="published", institution=p.institution
    ).order_by("subject", "title")
    return Response(
        CourseSerializer(
            [c for c in courses if course_is_assigned(p, c)], many=True
        ).data
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def course_detail(request, pk):
    if request.user.account_type == "student":
        p = student_profile(request.user)
        c = get_object_or_404(Course, pk=pk)
        if not course_is_assigned(p, c):
            return Response({"detail": "Course not available."}, status=404)
    else:
        m = membership_for_request(request)
        if not m or m.role not in ["owner", "admin", "teacher", "reviewer"]:
            return Response(
                {"detail": "Institution staff membership required."}, status=403
            )
        c = get_object_or_404(Course, pk=pk, institution=m.institution)
        if c.status != "published" and m.role not in [
            "owner",
            "admin",
            "teacher",
            "reviewer",
        ]:
            return Response({"detail": "Course not available."}, status=404)
    data = CourseSerializer(c).data
    data["lessons"] = LessonSerializer(c.lessons.all(), many=True).data
    return Response(data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def lesson_detail(request, pk):
    lesson = get_object_or_404(Lesson, pk=pk)
    if request.user.account_type == "student":
        p = student_profile(request.user)
        if not course_is_assigned(p, lesson.course):
            return Response({"detail": "Lesson not available."}, status=404)
        # Do not expose answer keys through the lesson read endpoint.
        data = LessonSerializer(lesson).data
        data["questions"] = [
            {
                "id": q.id,
                "prompt": q.prompt,
                "choices": q.choices,
                "points": q.points,
                "order": q.order,
            }
            for q in lesson.questions.all()
        ]
        return Response(data)
    m = membership_for_request(request)
    if (
        not m
        or m.role not in ["owner", "admin", "teacher", "reviewer"]
        or m.institution_id != lesson.course.institution_id
    ):
        return Response({"detail": "Not found."}, status=404)
    data = LessonSerializer(lesson).data
    data["questions"] = [
        {
            "id": q.id,
            "prompt": q.prompt,
            "choices": q.choices,
            "correct_index": q.correct_index,
            "explanation": q.explanation,
            "points": q.points,
        }
        for q in lesson.questions.all()
    ]
    return Response(data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def submit_quiz(request, lesson_id):
    if request.user.account_type != "student":
        return Response({"detail": "Student account required."}, status=403)
    p = student_profile(request.user)
    lesson = get_object_or_404(Lesson, pk=lesson_id)
    if lesson.content_type != "quiz" and not lesson.questions.exists():
        return Response({"detail": "This lesson has no quiz."}, status=400)
    if not course_is_assigned(p, lesson.course):
        return Response({"detail": "Lesson not available."}, status=404)
    answers = request.data.get("answers", {})
    if not isinstance(answers, dict):
        return Response(
            {
                "detail": "answers must be an object mapping question IDs to choice indexes."
            },
            status=400,
        )
    score = max_score = 0
    normalized = {}
    for q in lesson.questions.all():
        raw = answers.get(str(q.id), answers.get(q.id, -1))
        try:
            idx = int(raw)
        except (ValueError, TypeError):
            idx = -1
        if idx < -1 or idx >= len(q.choices):
            return Response(
                {"detail": "One or more answer choices are invalid."}, status=400
            )
        normalized[str(q.id)] = idx
        max_score += q.points
        if idx == q.correct_index:
            score += q.points
    with transaction.atomic():
        attempt = QuizAttempt.objects.create(
            student=p,
            lesson=lesson,
            answers=normalized,
            score=score,
            max_score=max_score,
        )
        RewardEvent.objects.get_or_create(
            student=p,
            event_key=f"quiz-complete-{lesson.pk}",
            defaults={"points": 5, "reason": "Completed a learning activity"},
        )
        LearningProgress.objects.update_or_create(
            student=p,
            lesson=lesson,
            defaults={
                "status": "completed",
                "percent": 100,
                "completed_at": timezone.now(),
            },
        )
        AuditEvent.objects.create(
            actor=request.user,
            institution=p.institution,
            action="quiz.submitted",
            object_type="QuizAttempt",
            object_id=str(attempt.pk),
            details={"score": score, "max_score": max_score},
        )
    return Response(
        {
            "attempt_id": attempt.pk,
            "score": score,
            "max_score": max_score,
            "feedback": [
                {
                    "question_id": q.id,
                    "correct": normalized.get(str(q.id)) == q.correct_index,
                    "explanation": q.explanation,
                }
                for q in lesson.questions.all()
            ],
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(["PUT", "PATCH"])
@permission_classes([IsAuthenticated])
def update_progress(request, lesson_id):
    if request.user.account_type != "student":
        return Response({"detail": "Student account required."}, status=403)
    p = student_profile(request.user)
    lesson = get_object_or_404(Lesson, pk=lesson_id)
    if not course_is_assigned(p, lesson.course):
        return Response({"detail": "Lesson not available."}, status=404)
    try:
        percent = max(0, min(99, int(request.data.get("percent", 0))))
    except (ValueError, TypeError):
        return Response({"detail": "percent must be an integer."}, status=400)
    try:
        pos = max(0, int(request.data.get("last_position", 0)))
    except (ValueError, TypeError):
        return Response({"detail": "last_position must be an integer."}, status=400)
    obj, _ = LearningProgress.objects.get_or_create(student=p, lesson=lesson)
    if obj.status != "completed":
        obj.status = "in_progress"
        obj.percent = percent
        obj.last_position = pos
        obj.save()
    return Response(ProgressSerializer(obj).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def my_progress(request):
    if request.user.account_type == "student":
        p = student_profile(request.user)
        qs = (
            LearningProgress.objects.filter(student=p)
            .select_related("lesson", "lesson__course")
            .order_by("-updated_at")
        )
    elif request.user.account_type == "adult":
        links = GuardianLink.objects.filter(
            guardian=request.user,
            verified_at__isnull=False,
            revoked_at__isnull=True,
            student__institution__status="approved",
            student__is_active=True,
            student__user__is_active=True,
        )
        if links.exists():
            qs = (
                LearningProgress.objects.filter(student__in=[l.student for l in links])
                .select_related("student", "lesson", "lesson__course")
                .order_by("-updated_at")
            )
        else:
            m = membership_for_request(request)
            if not m or m.role not in ["owner", "admin", "teacher", "reviewer"]:
                return Response(
                    {"detail": "Guardian link or staff membership required."},
                    status=403,
                )
            qs = (
                LearningProgress.objects.filter(student__institution=m.institution)
                .select_related("student", "lesson", "lesson__course")
                .order_by("-updated_at")
            )
    else:
        m = membership_for_request(request)
        if not m or m.role not in ["owner", "admin", "teacher", "reviewer"]:
            return Response({"detail": "Membership required."}, status=403)
        qs = (
            LearningProgress.objects.filter(student__institution=m.institution)
            .select_related("student", "lesson", "lesson__course")
            .order_by("-updated_at")
        )
    return Response(ProgressSerializer(qs[:500], many=True).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def institution_classes(request):
    m = membership_for_request(request)
    if not m or m.role not in ["owner", "admin", "teacher"]:
        return Response({"detail": "Insufficient permissions."}, status=403)
    qs = Classroom.objects.filter(institution=m.institution)
    if m.role == "teacher":
        qs = qs.filter(teachers=request.user)
    return Response(ClassroomSerializer(qs, many=True).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def guardian_children(request):
    if request.user.account_type != "adult":
        return Response({"detail": "Guardian account required."}, status=403)
    links = GuardianLink.objects.filter(
        guardian=request.user,
        verified_at__isnull=False,
        revoked_at__isnull=True,
        student__institution__status="approved",
        student__is_active=True,
        student__user__is_active=True,
    ).select_related("student__user", "student__classroom", "student__institution")
    return Response(
        [
            {
                "student_id": l.student_id,
                "display_name": l.student.user.display_name or l.student.user.username,
                "institution": l.student.institution.name,
                "classroom": l.student.classroom.name if l.student.classroom else None,
                "completed_lessons": LearningProgress.objects.filter(
                    student=l.student, status="completed"
                ).count(),
                "points": sum(r.points for r in l.student.reward_events.all()),
            }
            for l in links
        ]
    )
