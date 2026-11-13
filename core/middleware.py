class SecurityHeadersMiddleware:
    """Baseline browser hardening with a restrictive policy for the first-party web UI."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault("X-Content-Type-Options", "nosniff")
        response.setdefault("Referrer-Policy", "same-origin")
        response.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        response.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.setdefault("X-Frame-Options", "DENY")
        if not request.path.startswith("/admin/"):
            response.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; object-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; font-src 'self' data:; script-src 'self'",
            )
        if request.path.startswith("/student/"):
            response["Cache-Control"] = "no-store, private"
        return response


class ForcePasswordChangeMiddleware:
    """Require school-created temporary accounts to change their password before using the app."""

    EXEMPT_PREFIXES = (
        "/password/change/",
        "/logout/",
        "/admin/",
        "/static/",
        "/media/",
        "/health/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            user is not None
            and user.is_authenticated
            and getattr(user, "must_change_password", False)
            and not any(request.path.startswith(p) for p in self.EXEMPT_PREFIXES)
        ):
            from django.shortcuts import redirect

            return redirect("change_password")
        return self.get_response(request)
