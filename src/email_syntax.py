"""Bounded source-address matching; never synthesize a contact address."""
import re

# RFC-sized components and token boundaries prevent quadratic rescanning of
# minified/percent-encoded page tokens that contain no address separator.
EMAIL_RE=re.compile(r'(?i)(?<![\w.%+-])([A-Z0-9._%+-]{1,64}@[A-Z0-9.-]{1,253}\.[A-Z]{2,63})(?![\w.%+-])')
OBFUSCATED_EMAIL_RE=re.compile(r'(?i)(?<![\w.%+-])([a-z0-9._%+-]{1,64})\s*(?:\[at\]|\(at\)|\sat\s)\s*([a-z0-9.-]{1,253})\s*(?:\[dot\]|\(dot\)|\sdot\s)\s*([a-z]{2,63})\b')
