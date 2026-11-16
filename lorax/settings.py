"""
Django settings for Cooking with the Lorax.

All secrets and deployment-specific values come from the environment (`stack.env`,
loaded by python-decouple). See README.md for the full list of variable names.
"""
from pathlib import Path

from decouple import Csv, config
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config('SECRET_KEY')
DEBUG = config('DEBUG', default=False, cast=bool)

# Public URL used to build links in emails (client menu links, photos).
APP_BASE_URL = config('APP_BASE_URL', default='https://cookingwiththe.loraxglobal.com').rstrip('/')

ALLOWED_HOSTS = ['*']
CSRF_TRUSTED_ORIGINS = [APP_BASE_URL]

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True

# Google accounts that may sign in, seeded into the AllowedUser table on migrate. More can be added
# on the Admin page. Everyone listed here is an admin.
INITIAL_ADMIN_EMAILS = config('INITIAL_ADMIN_EMAILS', default='lweischedel@gmail.com,michael@carrell.us', cast=Csv())

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "kitchen",
]

SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "SCOPE": ["profile", "email"],
        "APP": {
            "client_id": config('GOOGLE_CLIENT_ID', default=''),
            "secret": config('GOOGLE_CLIENT_SECRET', default=''),
            "key": "",
        },
    }
}

LOGIN_URL = "/accounts/google/login/"
SOCIALACCOUNT_LOGIN_ON_GET = True
SOCIALACCOUNT_ONLY = True
ACCOUNT_EMAIL_VERIFICATION = "none"
# The proxy also answers on plain http, and Google only accepts the https callback.
ACCOUNT_DEFAULT_HTTP_PROTOCOL = "http" if DEBUG else "https"
ACCOUNT_ADAPTER = 'kitchen.adapter.ClosedAccountAdapter'
SOCIALACCOUNT_ADAPTER = 'kitchen.adapter.AllowListSocialAdapter'

MIDDLEWARE = [
    "allauth.account.middleware.AccountMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "kitchen.middleware.AllowedUserRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "lorax.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / 'templates'],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "kitchen.context_processors.ui",
            ],
        },
    },
]

WSGI_APPLICATION = "lorax.wsgi.application"

# The home server's Postgres (192.168.68.78). There is no SQLite fallback: tests also run on this
# server, in a throwaway test_cooking_with_the_lorax database that Django creates and drops.
if not config('DB_HOST', default=''):
    raise ImproperlyConfigured('DB_HOST is not set. Add the DB_* variables to stack.env (see README).')
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config('DB_NAME', default='cooking_with_the_lorax'),
        "USER": config('DB_USER'),
        "PASSWORD": config('DB_PASSWORD'),
        "HOST": config('DB_HOST'),
        "PORT": config('DB_PORT', default='5432'),
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = config('TIME_ZONE', default='America/Denver')
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTHENTICATION_BACKENDS = (
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
)

LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"

# Photo uploads (several phone photos per recipe import) can be large.
DATA_UPLOAD_MAX_MEMORY_SIZE = 60 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024

# Outbound email (client menus). Gmail SMTP with an app password works.
EMAIL_BACKEND = config('EMAIL_BACKEND', default='django.core.mail.backends.smtp.EmailBackend')
EMAIL_HOST = config('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='Cooking with the Lorax <meals@carrell.us>')
# Client replies to menu emails go here (the From address is whatever the SMTP account may send as).
MENU_REPLY_TO = config('MENU_REPLY_TO', default='lweischedel@gmail.com')

# Claude (recipe importer). ANTHROPIC_API_KEY is read by the SDK itself.
CLAUDE_MODEL = config('CLAUDE_MODEL', default='claude-opus-5-5')

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
