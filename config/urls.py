from django.contrib import admin
from django.urls import path, include
from core import views, api

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", views.home, name="home"),
    path("privacy/", views.privacy_page, name="privacy"),
    path("safety/", views.safety_page, name="safety"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("password/change/", views.change_password, name="change_password"),
    path("institutions/apply/", views.institution_apply, name="institution_apply"),
    path("guardians/sign-up/", views.guardian_signup, name="guardian_signup"),
    path("verify-email/<str:token>/", views.verify_email, name="verify_email"),
    path(
        "guardians/consent/<str:token>/",
        views.guardian_consent,
        name="guardian_consent",
    ),
    path(
        "guardians/links/<int:pk>/revoke/",
        views.guardian_revoke_link,
        name="guardian_revoke_link",
    ),
    path("dashboard/", views.dashboard, name="dashboard"),
    path(
        "platform/institutions/",
        views.platform_institutions,
        name="platform_institutions",
    ),
    path(
        "platform/institutions/<int:pk>/<str:decision>/",
        views.institution_decision,
        name="institution_decision",
    ),
    path("academic-years/", views.academic_years, name="academic_years"),
    path("classes/", views.classroom_list, name="classroom_list"),
    path("classes/new/", views.classroom_create, name="classroom_create"),
    path("students/", views.student_list, name="student_list"),
    path("students/new/", views.student_create, name="student_create"),
    path(
        "students/<int:pk>/class/",
        views.student_class_update,
        name="student_class_update",
    ),
    path(
        "staff/invitations/",
        views.staff_invitation_create,
        name="staff_invitation_create",
    ),
    path(
        "staff/memberships/<int:pk>/deactivate/",
        views.staff_membership_deactivate,
        name="staff_membership_deactivate",
    ),
    path(
        "invitations/accept/<str:token>/",
        views.invitation_accept,
        name="invitation_accept",
    ),
    path("courses/", views.course_list, name="course_list"),
    path("courses/new/", views.course_create, name="course_create"),
    path("courses/<int:pk>/", views.course_detail, name="course_detail"),
    path("courses/<int:pk>/edit/", views.course_edit, name="course_edit"),
    path(
        "courses/<int:course_pk>/lessons/new/",
        views.lesson_create,
        name="lesson_create",
    ),
    path(
        "lessons/<int:lesson_pk>/questions/new/",
        views.quiz_question_create,
        name="quiz_question_create",
    ),
    path("courses/<int:pk>/publish/", views.course_publish, name="course_publish"),
    path(
        "courses/<int:pk>/review/<str:decision>/",
        views.course_review_decision,
        name="course_review_decision",
    ),
    path(
        "courses/<int:course_pk>/report/",
        views.safety_report_create,
        name="safety_report_course",
    ),
    path(
        "courses/<int:course_pk>/lessons/<int:lesson_pk>/report/",
        views.safety_report_create,
        name="safety_report_lesson",
    ),
    path("safety/reports/", views.safety_report_list, name="safety_report_list"),
    path(
        "safety/reports/<int:pk>/update/",
        views.safety_report_update,
        name="safety_report_update",
    ),
    path("reports/", views.institution_reports, name="institution_reports"),
    path("assignments/", views.assignment_list, name="assignment_list"),
    path("assignments/new/", views.assignment_create, name="assignment_create"),
    path("student/", views.student_home, name="student_home"),
    path("student/courses/<int:pk>/", views.student_course, name="student_course"),
    path("student/lessons/<int:pk>/", views.student_lesson, name="student_lesson"),
    path("guardian/", views.guardian_dashboard, name="guardian_dashboard"),
    path("guardian/link/", views.guardian_link_create, name="guardian_link_create"),
    path("health/", views.health, name="health"),
    path("notifications/", views.notifications, name="notifications"),
    path(
        "announcements/create/", views.announcement_create, name="announcement_create"
    ),
    path(
        "api/schema/",
        __import__(
            "drf_spectacular.views", fromlist=["SpectacularAPIView"]
        ).SpectacularAPIView.as_view(),
        name="schema",
    ),
    path(
        "api/docs/",
        __import__(
            "drf_spectacular.views", fromlist=["SpectacularSwaggerView"]
        ).SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path(
        "api/redoc/",
        __import__(
            "drf_spectacular.views", fromlist=["SpectacularRedocView"]
        ).SpectacularRedocView.as_view(url_name="schema"),
        name="redoc",
    ),
    path("api/v1/me/", api.me, name="api_me"),
    path("api/v1/student/courses/", api.student_courses, name="api_student_courses"),
    path("api/v1/courses/<int:pk>/", api.course_detail, name="api_course_detail"),
    path("api/v1/lessons/<int:pk>/", api.lesson_detail, name="api_lesson_detail"),
    path(
        "api/v1/lessons/<int:lesson_id>/quiz/", api.submit_quiz, name="api_submit_quiz"
    ),
    path(
        "api/v1/lessons/<int:lesson_id>/progress/",
        api.update_progress,
        name="api_update_progress",
    ),
    path("api/v1/progress/", api.my_progress, name="api_my_progress"),
    path(
        "api/v1/institution/classes/",
        api.institution_classes,
        name="api_institution_classes",
    ),
    path(
        "api/v1/guardian/children/", api.guardian_children, name="api_guardian_children"
    ),
]
