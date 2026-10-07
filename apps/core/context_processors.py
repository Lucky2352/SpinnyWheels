from django.conf import settings


def frontend_config(request):
    return {
        "supabase_url": settings.SUPABASE_URL or "",
        "supabase_publishable_key": settings.SUPABASE_PUBLISHABLE_KEY or "",
        "api_base_url": "/api/",
    }