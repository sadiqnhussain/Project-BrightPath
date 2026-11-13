from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient
from .models import (
    Institution,
    Membership,
    Classroom,
    StudentProfile,
    Course,
    Lesson,
    QuizQuestion,
    CourseAssignment,
    LearningProgress,
)

User = get_user_model()


class TenantAndLearningSecurityTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.school = Institution.objects.create(
            name="North School",
            kind="school",
            slug="north-school",
            contact_email="office@north.example",
            status=Institution.Status.APPROVED,
        )
        self.other = Institution.objects.create(
            name="South School",
            kind="school",
            slug="south-school",
            contact_email="office@south.example",
            status=Institution.Status.APPROVED,
        )
        self.student_user = User.objects.create_user(
            username="learner",
            password="VeryStrong-Test-Pass-2026",
            account_type=User.AccountType.STUDENT,
            display_name="Learner",
        )
        self.profile = StudentProfile.objects.create(
            user=self.student_user, institution=self.school
        )
        Membership.objects.create(
            user=self.student_user,
            institution=self.school,
            role=Membership.Role.STUDENT,
        )
        self.teacher = User.objects.create_user(
            username="teacher",
            password="VeryStrong-Test-Pass-2026",
            account_type=User.AccountType.ADULT,
        )
        Membership.objects.create(
            user=self.teacher, institution=self.school, role=Membership.Role.TEACHER
        )
        self.course = Course.objects.create(
            institution=self.school,
            created_by=self.teacher,
            title="Science",
            summary="Short science course",
            subject="Science",
            grade_levels=[],
            status=Course.Status.PUBLISHED,
            published_at=timezone.now(),
        )
        self.lesson = Lesson.objects.create(
            course=self.course,
            title="Question time",
            content_type=Lesson.ContentType.QUIZ,
            body="Choose an answer",
            order=1,
        )
        self.question = QuizQuestion.objects.create(
            lesson=self.lesson,
            prompt="Which is a star?",
            choices=["Sun", "Moon"],
            correct_index=0,
            explanation="The Sun is a star.",
            order=1,
        )
        CourseAssignment.objects.create(
            course=self.course,
            institution=self.school,
            student=self.profile,
            assigned_by=self.teacher,
            status=CourseAssignment.Status.ACTIVE,
        )
        self.client.force_authenticate(self.student_user)

    def test_student_only_sees_assigned_courses(self):
        response = self.client.get("/api/v1/student/courses/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([x["id"] for x in response.data], [self.course.id])
        private = Course.objects.create(
            institution=self.school,
            created_by=self.teacher,
            title="Private",
            summary="Not assigned",
            subject="Science",
            status=Course.Status.PUBLISHED,
        )
        response = self.client.get(f"/api/v1/courses/{private.id}/")
        self.assertEqual(response.status_code, 404)

    def test_student_lesson_api_does_not_expose_answer_key(self):
        response = self.client.get(f"/api/v1/lessons/{self.lesson.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("correct_index", response.data["questions"][0])
        self.assertNotIn("explanation", response.data["questions"][0])

    def test_server_scores_quiz_and_persists_progress(self):
        response = self.client.post(
            f"/api/v1/lessons/{self.lesson.id}/quiz/",
            {"answers": {str(self.question.id): 0}},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["score"], 1)
        self.assertTrue(
            LearningProgress.objects.filter(
                student=self.profile, lesson=self.lesson, status="completed"
            ).exists()
        )

    def test_assignment_requires_exactly_one_target(self):
        assignment = CourseAssignment(
            course=self.course, institution=self.school, assigned_by=self.teacher
        )
        with self.assertRaises(Exception):
            assignment.full_clean()

    def test_individual_assignment_does_not_leak_to_other_student_without_class(self):
        other_user = User.objects.create_user(
            username="other-learner",
            password="VeryStrong-Test-Pass-2026",
            account_type=User.AccountType.STUDENT,
        )
        StudentProfile.objects.create(
            user=other_user, institution=self.school, classroom=None
        )
        self.client.force_authenticate(other_user)
        response = self.client.get(f"/api/v1/courses/{self.course.id}/")
        self.assertEqual(response.status_code, 404)

    def test_cross_institution_course_is_not_visible(self):
        foreign = Course.objects.create(
            institution=self.other,
            created_by=self.teacher,
            title="Foreign course",
            summary="Private",
            subject="Math",
            status=Course.Status.PUBLISHED,
        )
        response = self.client.get(f"/api/v1/courses/{foreign.id}/")
        self.assertEqual(response.status_code, 404)
