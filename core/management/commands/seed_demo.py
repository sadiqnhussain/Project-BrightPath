from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.conf import settings
from django.utils.text import slugify
from core.models import (
    Institution,
    Membership,
    AcademicYear,
    Classroom,
    StudentProfile,
    Course,
    Lesson,
    QuizQuestion,
    CourseAssignment,
    GuardianLink,
)

User = get_user_model()


class Command(BaseCommand):
    help = "Create clearly marked local demo accounts and sample learning content. Never run on production."

    
    def handle(self, *args, **opts):
        password = "DemoPass1234"
        # for real production environment
        # if not settings.DEBUG:
        #     self.stderr.write(
        #         self.style.ERROR("Refusing to seed demo accounts when DEBUG is off.")
        #     )
        #     return

        def user(username, email, name, kind):
            obj, created = User.objects.get_or_create(
                username=username,
                defaults={"email": email, "display_name": name, "account_type": kind},
            )
            if created:
                obj.set_password(password)
                obj.email_verified = True
                obj.save()
            return obj

        
        admin = user(
            "school-admin",
            "admin@example.invalid",
            "School Admin",
            User.AccountType.ADULT,
        )

        inst, _ = Institution.objects.get_or_create(
            slug="demo-learning-school",
            defaults={
                "name": "Demo Learning Academy",
                "kind": Institution.Kind.SCHOOL,
                "contact_email": "admin@example.invalid",
                "country_or_region": "Afghanistan",
                "description": (
                    "A demonstration learning institution showcasing "
                    "courses, classrooms, assignments, quizzes and reporting."
                ),
                "status": Institution.Status.APPROVED,
                "approved_by": "Platfrom adminstration",
                "approved_at": timezone.now(),
            },
        )

        Membership.objects.get_or_create(
            user=admin,
            institution=inst,
            defaults={"role": Membership.Role.OWNER},
        )

        year, _ = AcademicYear.objects.get_or_create(
            institution=inst,
            name="2024-2025",
            defaults={"is_active": True},
        )

        teacher_data = [
            ("teacher01", "alex.carter@example.invalid", "Alex Carter"),
            ("teacher02", "sarah.johnson@example.invalid", "Sarah Johnson"),
            ("teacher03", "michael.brown@example.invalid", "Michael Brown"),
        ]

        teachers = []

        for username, email, name in teacher_data:
            teacher = user(
                username,
                email,
                name,
                User.AccountType.ADULT,
            )

            Membership.objects.get_or_create(
                user=teacher,
                institution=inst,
                defaults={"role": Membership.Role.TEACHER},
            )

            teachers.append(teacher)

        teacher_science = teachers[0]
        teacher_math = teachers[1]
        teacher_coding = teachers[2]

        classroom_4, _ = Classroom.objects.get_or_create(
            institution=inst,
            academic_year=year,
            name="Grade 4 · Curious Owls",
            defaults={
                "grade_level": "Grade 4",
                "section": "Curious Owls",
                "age_min": 9,
                "age_max": 11,
            },
        )

        classroom_5, _ = Classroom.objects.get_or_create(
            institution=inst,
            academic_year=year,
            name="Grade 5 · Future Innovators",
            defaults={
                "grade_level": "Grade 5",
                "section": "Future Innovators",
                "age_min": 10,
                "age_max": 12,
            },
        )

        classroom_4.teachers.add(
            teacher_science,
            teacher_math,
        )

        classroom_5.teachers.add(
            teacher_math,
            teacher_coding,
        )

        guardians = []

        for i in range(1, 6):
            g = user(
                f"guardian{i:02d}",
                f"guardian{i:02d}@example.invalid",
                f"Guardian {i}",
                User.AccountType.ADULT,
            )
            guardians.append(g)

        student_names = [
            "Emma Wilson",
            "Noah Davis",
            "Olivia Moore",
            "Liam Taylor",
            "Ava Anderson",
            "Ethan Thomas",
            "Sophia Martin",
            "Mason White",
            "Isabella Clark",
            "James Walker",
        ]

        avatars = ["star", "rocket", "planet", "book", "trophy"]

        student_profiles = []

        for idx, name in enumerate(student_names, start=1):
            student_user = user(
                f"student{idx:02d}",
                f"student{idx:02d}@example.invalid",
                name,
                User.AccountType.STUDENT,
            )

            Membership.objects.get_or_create(
                user=student_user,
                institution=inst,
                defaults={"role": Membership.Role.STUDENT},
            )

            classroom = classroom_4 if idx <= 5 else classroom_5

            profile, _ = StudentProfile.objects.get_or_create(
                user=student_user,
                defaults={
                    "institution": inst,
                    "classroom": classroom,
                    "student_code": f"DLA-{idx:03d}",
                    "avatar": avatars[idx % len(avatars)],
                    "preferred_language": "en",
                },
            )

            student_profiles.append(profile)

        for guardian, profile in zip(guardians, student_profiles[:5]):
            GuardianLink.objects.get_or_create(
                guardian=guardian,
                student=profile,
                defaults={
                    "relationship": "Parent",
                    "verified_at": timezone.now(),
                    "consent_recorded_at": timezone.now(),
                    "consent_policy_version": "demo-v1",
                },
            )

        course_configs = [
            {
                "title": "The Curious Science Lab",
                "subject": "Science",
                "teacher": teacher_science,
                "emoji": "🔬",
                "video": "https://www.youtube.com/watch?v=Frjdj0U8T7k",
            },
            {
                "title": "Mathematics in Everyday Life",
                "subject": "Mathematics",
                "teacher": teacher_math,
                "emoji": "➗",
                "video": "https://www.youtube.com/watch?v=d_qvLDhkg00",
            },
            {
                "title": "Introduction to Coding with Scratch",
                "subject": "Computer Studies",
                "teacher": teacher_coding,
                "emoji": "💻",
                "video": "https://www.youtube.com/watch?v=jXUZaf5D12A",
            },
            {
                "title": "Environmental Awareness",
                "subject": "Environmental Science",
                "teacher": teacher_science,
                "emoji": "🌍",
                "video": "https://www.youtube.com/watch?v=OasbYWF4_S8",
            },
            {
                "title": "Creative Writing for Young Learners",
                "subject": "English",
                "teacher": teacher_math,
                "emoji": "✍️",
                "video": "https://www.youtube.com/watch?v=NFz4nUEA4wY",
            },
        ]

        courses = []

        for config in course_configs:

            course, _ = Course.objects.get_or_create(
                institution=inst,
                title=config["title"],
                defaults={
                    "created_by": config["teacher"],
                    "summary": f"A rich introduction to {config['subject']}.",
                    "subject": config["subject"],
                    "language": "en",
                    "grade_levels": ["Grade 4", "Grade 5"],
                    "learning_objectives": [
                        "Understand core concepts",
                        "Apply learning through activities",
                        "Complete quizzes successfully",
                    ],
                    "estimated_minutes": 60,
                    "emoji": config["emoji"],
                    "status": Course.Status.PUBLISHED,
                    "published_at": timezone.now(),
                },
            )

            lessons = [
                {
                    "title": "Introduction",
                    "type": Lesson.ContentType.TEXT,
                    "body": f"Welcome to {config['title']}. Learn key concepts through guided learning.",
                    "media": "",
                },
                {
                    "title": "Watch and Learn",
                    "type": Lesson.ContentType.VIDEO,
                    "body": "Watch this educational video.",
                    "media": config["video"],
                },
                {
                    "title": "Hands-on Activity",
                    "type": Lesson.ContentType.ACTIVITY,
                    "body": "Complete the activity and discuss your observations.",
                    "media": "",
                },
                {
                    "title": "Knowledge Check",
                    "type": Lesson.ContentType.QUIZ,
                    "body": "Answer the quiz questions below.",
                    "media": "",
                },
            ]

            quiz_lesson = None

            for order, lesson_data in enumerate(lessons, start=1):

                lesson, _ = Lesson.objects.get_or_create(
                    course=course,
                    order=order,
                    defaults={
                        "title": lesson_data["title"],
                        "content_type": lesson_data["type"],
                        "body": lesson_data["body"],
                        "media_url": lesson_data["media"],
                        "duration_minutes": 10,
                    },
                )

                if lesson.content_type == Lesson.ContentType.QUIZ:
                    quiz_lesson = lesson

            if quiz_lesson:
                questions = [
                    (
                        "What is the most important lesson topic?",
                        [
                            "The main concept",
                            "Nothing",
                            "Random guessing",
                            "Skipping lessons",
                        ],
                    ),
                    (
                        "Why should students practice?",
                        [
                            "To improve understanding",
                            "To avoid learning",
                            "To waste time",
                            "No reason",
                        ],
                    ),
                    (
                        "What should you do if you are confused?",
                        [
                            "Ask questions",
                            "Give up",
                            "Ignore the lesson",
                            "Skip the course",
                        ],
                    ),
                ]

                for q_order, (prompt, choices) in enumerate(questions, start=1):
                    QuizQuestion.objects.get_or_create(
                        lesson=quiz_lesson,
                        order=q_order,
                        defaults={
                            "prompt": prompt,
                            "choices": choices,
                            "correct_index": 0,
                            "explanation": "Review the lesson material.",
                            "points": 1,
                        },
                    )

            courses.append(course)

        for course in courses:

            for classroom in [classroom_4, classroom_5]:

                CourseAssignment.objects.get_or_create(
                    course=course,
                    institution=inst,
                    classroom=classroom,
                    student=None,
                    defaults={
                        "assigned_by": course.created_by,
                        "status": CourseAssignment.Status.ACTIVE,
                    },
                )

        self.stdout.write(
            self.style.SUCCESS(
                (
                    "Demo data ready. "
                    "Accounts created: "
                    "school-admin, "
                    "teacher01-teacher03, "
                    "student01-student10, "
                    "guardian01-guardian05. "
                    "Created 5 courses, 20 lessons, "
                    "and 2 classrooms sample data."
                )
            )
        )
