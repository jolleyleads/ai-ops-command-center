"""Offline configuration readiness; no providers are called and no secret is printed."""
import json
import os
import sys


def check_configuration(env=None):
    env = os.environ if env is None else env
    missing = [name for name in ('DATABASE_URL', 'SECRET_KEY', 'OPERATOR_CONTROL_TOKEN',
               'QUALIFICATION_SIGNING_KEY_VERSION', 'QUALIFICATION_SIGNING_KEYS',
               'GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET', 'GMAIL_FROM_EMAIL') if not env.get(name)]
    invalid = []
    if env.get('DATABASE_URL') and not env['DATABASE_URL'].startswith(('postgresql:', 'postgresql+', 'postgres:')):
        invalid.append('PERSISTENT_SHARED_POSTGRES_REQUIRED')
    if env.get('SECRET_KEY') == 'dev-secret-key':invalid.append('SECRET_KEY_DEFAULT')
    hunter = env.get('HUNTER_MAILBOX_VERIFICATION_ENABLED', '').lower() == 'true'
    if hunter:
        missing += [name for name in ('HUNTER_API_KEY', 'HUNTER_ACCOUNT_EMAIL') if not env.get(name)]
    return {'ok': not missing and not invalid, 'missing_settings': missing,
            'configuration_errors': invalid, 'hunter_enabled': hunter,
            'oauth_connection': 'verify persisted connection separately',
            'live_workflow_verified': False}


if __name__ == '__main__':
    result = check_configuration()
    print(json.dumps(result))
    sys.exit(0 if result['ok'] else 1)
