import os
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def load_local_env(path):
    """Load ignored local values without overriding deployed environment variables."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_local_env(BASE_DIR / ".env")
DEBUG = os.environ.get("DJANGO_DEBUG", "true").lower() == "true"
BUILTASUPPLY_DEMO_WEBHOOK_SECRET = os.environ.get("BUILTASUPPLY_DEMO_WEBHOOK_SECRET")
# Server-to-server token for the narrowly scoped RealEstateDemo delivery-status
# endpoint. Keep this value only in deployment environment configuration.
REALESTATE_STATUS_API_TOKEN = os.environ.get("REALESTATE_STATUS_API_TOKEN", "")
SECRET_KEY = os.environ.get("BUILTASUPPLY_SECRET_KEY")
if not SECRET_KEY:
    if not DEBUG: raise ImproperlyConfigured("BUILTASUPPLY_SECRET_KEY must be set outside development.")
    SECRET_KEY = "unsafe-development-key-not-for-production"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if origin.strip()]
INSTALLED_APPS = [
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes", "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles", "rest_framework",
    "apps.accounts", "apps.customers", "apps.suppliers", "apps.memberships", "apps.audit", "apps.catalog", "apps.inventory", "apps.carts", "apps.orders", "apps.payments", "apps.wallets", "apps.payouts", "apps.core", "apps.operations", "apps.notifications", "apps.integrations",
]
MIDDLEWARE = ["django.middleware.security.SecurityMiddleware", "django.contrib.sessions.middleware.SessionMiddleware", "django.middleware.common.CommonMiddleware", "django.middleware.csrf.CsrfViewMiddleware", "django.contrib.auth.middleware.AuthenticationMiddleware", "apps.accounts.middleware.AccountStatusMiddleware", "django.contrib.messages.middleware.MessageMiddleware", "django.middleware.clickjacking.XFrameOptionsMiddleware"]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "DIRS": [BASE_DIR / "templates"], "APP_DIRS": True, "OPTIONS": {"context_processors": ["django.template.context_processors.request", "django.contrib.auth.context_processors.auth", "django.contrib.messages.context_processors.messages", "apps.notifications.context_processors.notification_summary"]}}]
WSGI_APPLICATION = "config.wsgi.application"
database_url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
if database_url:
    parsed_database_url = urlparse(database_url)
    if parsed_database_url.scheme not in {"postgres", "postgresql"} or not parsed_database_url.hostname or not parsed_database_url.path:
        raise ImproperlyConfigured("DATABASE_URL must be a valid PostgreSQL connection URL.")
    database_query = parse_qs(parsed_database_url.query)
    DATABASES = {"default": {"ENGINE": "django.db.backends.postgresql", "NAME": unquote(parsed_database_url.path.lstrip("/")), "USER": unquote(parsed_database_url.username or ""), "PASSWORD": unquote(parsed_database_url.password or ""), "HOST": parsed_database_url.hostname, "PORT": parsed_database_url.port or 5432, "CONN_MAX_AGE": 60, "OPTIONS": {"sslmode": database_query.get("sslmode", ["require"])[0]}}}
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.postgresql" if os.environ.get("POSTGRES_DB") else "django.db.backends.sqlite3", "NAME": os.environ.get("POSTGRES_DB", BASE_DIR / "db.sqlite3"), "USER": os.environ.get("POSTGRES_USER", ""), "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""), "HOST": os.environ.get("POSTGRES_HOST", ""), "PORT": os.environ.get("POSTGRES_PORT", "")}}
AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["apps.accounts.backends.ActiveUserModelBackend"]
LOGIN_URL, LOGIN_REDIRECT_URL, LOGOUT_REDIRECT_URL = "accounts:login", "accounts:profile", "accounts:login"
LANGUAGE_CODE, TIME_ZONE, USE_I18N, USE_TZ = "en-us", "Asia/Manila", True, True
STATIC_URL, STATIC_ROOT = "static/", BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.PBKDF2PasswordHasher"]
AUTH_PASSWORD_VALIDATORS = [{"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"}, {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}}, {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"}, {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"}]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "no-reply@builtasupply.local")
SESSION_COOKIE_HTTPONLY, SESSION_COOKIE_SECURE, CSRF_COOKIE_SECURE = True, not DEBUG, not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF, SECURE_REFERRER_POLICY, X_FRAME_OPTIONS = True, "same-origin", "DENY"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = not DEBUG
SECURE_HSTS_SECONDS = 31_536_000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = False
REST_FRAMEWORK = {"DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"], "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"]}
